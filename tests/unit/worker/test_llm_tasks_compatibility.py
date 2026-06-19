"""LLM task backward-compatibility tests.

职责：验证 TaskIQ LLM 任务入口支持新旧两种参数格式。
边界：使用 mock 替代真实 workflow，不连接 Redis 或 broker。
"""

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.requires_taskiq


def _make_generation_payload() -> dict:
    import uuid

    return {"session_id": str(uuid.uuid4()), "query_text": "hello"}


def _make_stream_positional_args() -> tuple:
    import uuid

    return (
        _make_generation_payload(),
        "stream:test-channel",
        {"traceparent": "00-test"},
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        "lock:test",
    )


def _make_nonstream_positional_args() -> tuple:
    import uuid

    return (
        _make_generation_payload(),
        {"traceparent": "00-test"},
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        "lock:test",
    )


def _make_stream_result():
    from backend.models.schemas.chat.payloads import StreamGenerationResult

    return StreamGenerationResult(success=True, output="answer")


async def test_stream_task_unpacks_new_payload_dict() -> None:
    """New format: single LLMTaskPayload dict as args[0]."""
    from backend.models.schemas.chat.payloads import LLMTaskPayload
    from backend.worker.tasks.llm_tasks import generate_llm_stream_task

    gen_payload = _make_generation_payload()
    task_payload = LLMTaskPayload(
        generation_payload=gen_payload,
        channel="stream:test-ch",
        trace_context={"traceparent": "00-test"},
        assistant_message_id="msg-123",
        user_id="user-456",
        idempotency_lock_key="lock:abc",
    )
    payload_dict = task_payload.model_dump(mode="json")

    with (
        patch(
            "backend.worker.tasks.llm_tasks._generate_llm_stream_task",
            new_callable=AsyncMock,
            return_value=_make_stream_result(),
        ) as mock_inner,
        patch("backend.worker.tasks.llm_tasks.use_trace_context"),
        patch("backend.worker.tasks.llm_tasks.set_langfuse_trace_metadata"),
        patch("backend.worker.tasks.llm_tasks.langfuse_generation"),
    ):
        await generate_llm_stream_task(payload_dict)

    mock_inner.assert_awaited_once()
    call_kwargs = mock_inner.call_args.kwargs
    assert call_kwargs["channel"] == "stream:test-ch"
    assert call_kwargs["assistant_message_id"] == "msg-123"
    assert call_kwargs["user_id"] == "user-456"
    assert call_kwargs["idempotency_lock_key"] == "lock:abc"


async def test_stream_task_unpacks_old_positional_args() -> None:
    """Old format: multiple positional args."""
    from backend.worker.tasks.llm_tasks import generate_llm_stream_task

    gen_payload, channel, trace_ctx, msg_id, user_id, lock_key = (
        _make_stream_positional_args()
    )

    with (
        patch(
            "backend.worker.tasks.llm_tasks._generate_llm_stream_task",
            new_callable=AsyncMock,
            return_value=_make_stream_result(),
        ) as mock_inner,
        patch("backend.worker.tasks.llm_tasks.use_trace_context"),
        patch("backend.worker.tasks.llm_tasks.set_langfuse_trace_metadata"),
        patch("backend.worker.tasks.llm_tasks.langfuse_generation"),
    ):
        await generate_llm_stream_task(
            gen_payload, channel, trace_ctx, msg_id, user_id, lock_key
        )

    mock_inner.assert_awaited_once()
    call_kwargs = mock_inner.call_args.kwargs
    assert call_kwargs["channel"] == channel
    assert call_kwargs["assistant_message_id"] == msg_id
    assert call_kwargs["user_id"] == user_id
    assert call_kwargs["idempotency_lock_key"] == lock_key


async def test_stream_task_passes_external_context_provider_to_workflow() -> None:
    from backend.models.schemas.chat.payloads import LLMTaskPayload
    from backend.worker.tasks.llm_tasks import generate_llm_stream_task

    gen_payload = _make_generation_payload()
    task_payload = LLMTaskPayload(
        generation_payload=gen_payload,
        channel="stream:test-ch",
        trace_context={"traceparent": "00-test"},
        assistant_message_id="msg-123",
        user_id="user-456",
        idempotency_lock_key="lock:abc",
    )
    payload_dict = task_payload.model_dump(mode="json")

    fake_provider = AsyncMock()
    with (
        patch(
            "backend.worker.tasks.llm_tasks._generate_llm_stream_task",
            new_callable=AsyncMock,
            return_value=_make_stream_result(),
        ) as mock_inner,
        patch("backend.worker.tasks.llm_tasks.use_trace_context"),
        patch("backend.worker.tasks.llm_tasks.set_langfuse_trace_metadata"),
        patch("backend.worker.tasks.llm_tasks.langfuse_generation"),
        patch(
            "backend.worker.tasks.llm_tasks.get_worker_external_context_provider",
            return_value=fake_provider,
        ),
    ):
        await generate_llm_stream_task(payload_dict)

    mock_inner.assert_awaited_once()


async def test_nonstream_task_unpacks_new_payload_dict() -> None:
    from backend.models.schemas.chat.payloads import GenerationResult, LLMTaskPayload
    from backend.worker.tasks.llm_tasks import generate_llm_nonstream_task

    gen_payload = _make_generation_payload()
    task_payload = LLMTaskPayload(
        generation_payload=gen_payload,
        trace_context={"traceparent": "00-test"},
        assistant_message_id="msg-789",
        user_id="user-012",
        idempotency_lock_key="lock:def",
    )
    payload_dict = task_payload.model_dump(mode="json")

    expected = GenerationResult(success=True, content="answer")
    with (
        patch(
            "backend.worker.tasks.llm_tasks._generate_llm_nonstream_task",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_inner,
        patch("backend.worker.tasks.llm_tasks.use_trace_context"),
        patch("backend.worker.tasks.llm_tasks.set_langfuse_trace_metadata"),
        patch("backend.worker.tasks.llm_tasks.langfuse_generation"),
    ):
        result = await generate_llm_nonstream_task(payload_dict)

    assert result.success is True
    mock_inner.assert_awaited_once()
    call_kwargs = mock_inner.call_args.kwargs
    assert call_kwargs["assistant_message_id"] == "msg-789"
    assert call_kwargs["user_id"] == "user-012"
    assert call_kwargs["idempotency_lock_key"] == "lock:def"


async def test_nonstream_task_unpacks_old_positional_args() -> None:
    """Old format: multiple positional args."""
    from backend.models.schemas.chat.payloads import GenerationResult
    from backend.worker.tasks.llm_tasks import generate_llm_nonstream_task

    gen_payload, trace_ctx, msg_id, user_id, lock_key = (
        _make_nonstream_positional_args()
    )

    expected = GenerationResult(success=True, content="answer")
    with (
        patch(
            "backend.worker.tasks.llm_tasks._generate_llm_nonstream_task",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_inner,
        patch("backend.worker.tasks.llm_tasks.use_trace_context"),
        patch("backend.worker.tasks.llm_tasks.set_langfuse_trace_metadata"),
        patch("backend.worker.tasks.llm_tasks.langfuse_generation"),
    ):
        result = await generate_llm_nonstream_task(
            gen_payload, trace_ctx, msg_id, user_id, lock_key
        )

    assert result.success is True
    mock_inner.assert_awaited_once()
    call_kwargs = mock_inner.call_args.kwargs
    assert call_kwargs["assistant_message_id"] == msg_id
    assert call_kwargs["user_id"] == user_id
    assert call_kwargs["idempotency_lock_key"] == lock_key
