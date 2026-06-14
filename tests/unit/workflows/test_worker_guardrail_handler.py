"""WorkerGuardrailHandler unit tests — input block, RAG refusal, idempotency lock.

职责：验证 WorkerGuardrailHandler 的流式/非流式护栏拦截和 RAG 拒答后的
Redis 发布、持久化调用和幂等锁写入；边界：不启动 HTTP stack 或真实 Redis；副作用：无。
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from backend.services.chat_safety_metadata import (
    INJECTION_REFUSAL_MESSAGE,
    SAFETY_REFUSAL_MESSAGE,
    GuardrailDecision,
    GuardrailReason,
    ResponseOutcome,
)

pytestmark = pytest.mark.asyncio


def _make_handler(
    *,
    stream_publisher=None,
    count_output_tokens=lambda c: len(c),
):
    from backend.application.chat.worker_guardrail_handler import WorkerGuardrailHandler

    persistence_handler = AsyncMock(
        spec=["persist_success", "write_idempotency_message"]
    )
    persistence_handler.persist_success = AsyncMock()
    persistence_handler.write_idempotency_message = AsyncMock()

    handler = WorkerGuardrailHandler(
        persistence_handler=persistence_handler,
        stream_publisher=stream_publisher,
        count_output_tokens=count_output_tokens,
    )
    return handler, persistence_handler


async def test_stream_input_block_publishes_refusal_and_persists() -> None:
    publisher = AsyncMock()
    handler, persistence = _make_handler(stream_publisher=publisher)

    msg_id = uuid.uuid4()
    user_id = uuid.uuid4()
    decision = GuardrailDecision(triggered=True, reason="permission_risk")

    await handler.handle_stream_input_block(
        channel="stream:test",
        assistant_message_id=msg_id,
        user_id=user_id,
        input_decision=decision,
        start_time=1.0,
        idempotency_lock_key="lock:1",
    )

    publisher.publish_chunk.assert_awaited_once_with(
        "stream:test", SAFETY_REFUSAL_MESSAGE
    )
    persistence.persist_success.assert_awaited_once()
    kwargs = persistence.persist_success.call_args.kwargs
    assert kwargs["content"] == SAFETY_REFUSAL_MESSAGE
    assert kwargs["tokens_input"] == 0
    assert kwargs["message_metadata"]["response_outcome"] == ResponseOutcome.BLOCKED
    assert kwargs["message_metadata"]["guardrail"]["input"]["triggered"] is True
    persistence.write_idempotency_message.assert_awaited_once_with(
        idempotency_lock_key="lock:1",
        assistant_message_id=msg_id,
    )


async def test_stream_input_block_skips_publish_when_no_publisher() -> None:
    handler, persistence = _make_handler(stream_publisher=None)

    await handler.handle_stream_input_block(
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        input_decision=GuardrailDecision(triggered=True, reason="risk"),
        start_time=1.0,
        idempotency_lock_key=None,
    )

    persistence.persist_success.assert_awaited_once()


async def test_stream_input_block_skips_idempotency_when_key_missing() -> None:
    handler, persistence = _make_handler()

    await handler.handle_stream_input_block(
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        input_decision=GuardrailDecision(triggered=True, reason="risk"),
        start_time=1.0,
        idempotency_lock_key=None,
    )

    persistence.write_idempotency_message.assert_not_awaited()


async def test_stream_refusal_publishes_rag_refusal_and_persists() -> None:
    publisher = AsyncMock()
    handler, persistence = _make_handler(stream_publisher=publisher)

    msg_id = uuid.uuid4()
    search_ctx = {"rag_refusal": True, "reason": "no hits"}

    await handler.handle_stream_refusal(
        channel="stream:rag",
        assistant_message_id=msg_id,
        user_id=uuid.uuid4(),
        search_context=search_ctx,
        start_time=2.0,
        idempotency_lock_key="lock:2",
    )

    from backend.config.ai_settings import ai_settings

    publisher.publish_chunk.assert_awaited_once_with(
        "stream:rag", ai_settings.RAG_REFUSAL_MESSAGE
    )
    persistence.persist_success.assert_awaited_once()
    kwargs = persistence.persist_success.call_args.kwargs
    assert kwargs["tokens_input"] == 0
    assert kwargs["search_context"] == search_ctx
    assert kwargs["message_metadata"]["response_outcome"] == ResponseOutcome.REFUSED
    persistence.write_idempotency_message.assert_awaited_once()


async def test_stream_refusal_uses_planner_message_and_metadata() -> None:
    publisher = AsyncMock()
    handler, persistence = _make_handler(stream_publisher=publisher)
    search_ctx = {"planner_refusal": True, "reason": "planner refused"}

    await handler.handle_stream_refusal(
        channel="stream:planner",
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        search_context=search_ctx,
        start_time=2.0,
        idempotency_lock_key=None,
    )

    from backend.config.ai_settings import ai_settings

    publisher.publish_chunk.assert_awaited_once_with(
        "stream:planner", ai_settings.RAG_PLANNER_REFUSAL_MESSAGE
    )
    kwargs = persistence.persist_success.call_args.kwargs
    assert kwargs["content"] == ai_settings.RAG_PLANNER_REFUSAL_MESSAGE
    assert (
        kwargs["message_metadata"]["badcase"]["reason"] == "planner_preflight_refusal"
    )


async def test_nonstream_input_block_returns_result_and_persists() -> None:
    handler, persistence = _make_handler()

    msg_id = uuid.uuid4()
    decision = GuardrailDecision(triggered=True, reason="privacy")

    result = await handler.handle_nonstream_input_block(
        assistant_message_id=msg_id,
        user_id=uuid.uuid4(),
        input_decision=decision,
        start_time=1.0,
        idempotency_lock_key="lock:3",
    )

    assert result.success is True
    assert result.content == SAFETY_REFUSAL_MESSAGE
    assert result.tokens_input == 0
    persistence.persist_success.assert_awaited_once()
    persistence.write_idempotency_message.assert_awaited_once()


async def test_nonstream_refusal_returns_result_with_search_context() -> None:
    handler, persistence = _make_handler()

    search_ctx = {"rag_refusal": True, "reason": "low score"}
    result = await handler.handle_nonstream_refusal(
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        search_context=search_ctx,
        start_time=1.0,
        idempotency_lock_key=None,
    )

    assert result.success is True
    assert result.search_context == search_ctx
    persistence.persist_success.assert_awaited_once()
    persistence.write_idempotency_message.assert_not_awaited()


async def test_nonstream_refusal_uses_planner_message_and_metadata() -> None:
    handler, persistence = _make_handler()
    search_ctx = {"planner_refusal": True, "reason": "planner refused"}

    result = await handler.handle_nonstream_refusal(
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        search_context=search_ctx,
        start_time=1.0,
        idempotency_lock_key=None,
    )

    from backend.config.ai_settings import ai_settings

    assert result.content == ai_settings.RAG_PLANNER_REFUSAL_MESSAGE
    kwargs = persistence.persist_success.call_args.kwargs
    assert (
        kwargs["message_metadata"]["badcase"]["reason"] == "planner_preflight_refusal"
    )


async def test_idempotency_lock_skipped_when_message_id_none() -> None:
    handler, persistence = _make_handler()

    await handler.handle_stream_input_block(
        channel="stream:test",
        assistant_message_id=None,
        user_id=uuid.uuid4(),
        input_decision=GuardrailDecision(triggered=True, reason="risk"),
        start_time=1.0,
        idempotency_lock_key="lock:4",
    )

    persistence.persist_success.assert_awaited_once()
    persistence.write_idempotency_message.assert_not_awaited()


# ── Injection risk refusal message ──────────────────────────────────


async def test_stream_input_block_uses_injection_refusal_for_injection_risk() -> None:
    publisher = AsyncMock()
    handler, persistence = _make_handler(stream_publisher=publisher)

    decision = GuardrailDecision(
        triggered=True, reason=GuardrailReason.INJECTION_RISK.value
    )
    await handler.handle_stream_input_block(
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        input_decision=decision,
        start_time=1.0,
        idempotency_lock_key=None,
    )

    publisher.publish_chunk.assert_awaited_once_with(
        "stream:test", INJECTION_REFUSAL_MESSAGE
    )
    kwargs = persistence.persist_success.call_args.kwargs
    assert kwargs["content"] == INJECTION_REFUSAL_MESSAGE


async def test_nonstream_input_block_uses_injection_refusal_for_injection_risk() -> (
    None
):
    handler, persistence = _make_handler()

    decision = GuardrailDecision(
        triggered=True, reason=GuardrailReason.INJECTION_RISK.value
    )
    result = await handler.handle_nonstream_input_block(
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        input_decision=decision,
        start_time=1.0,
        idempotency_lock_key=None,
    )

    assert result.content == INJECTION_REFUSAL_MESSAGE
