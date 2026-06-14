"""Worker idempotency and error-path tests — lock write, lock cleanup, done guarantee.

职责：验证 worker 生成流程中幂等锁写入/清理、错误路径下的 Redis 发布和
done 事件保证等关键路径；边界：不启动 HTTP stack、不连接真实 Redis/LLM；副作用：无。
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from backend.application.chat.stream_events import (
    encode_done_event,
    encode_error_event,
    encode_started_event,
)
from backend.application.chat.worker_generation_workflow import (
    LLMGenerationWorkerWorkflow,
)
from backend.application.chat.worker_persistence_handler import WorkerPersistenceHandler
from backend.core.exceptions import app_service_error
from backend.models.schemas.chat.dto import LLMResultDTO
from backend.models.schemas.chat.payloads import GenerationPayload
from tests.unit.workflows.conftest import FakeChatUow

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.set_calls: list[tuple[str, str, int]] = []
        self.deleted: list[str] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    async def set(self, key: str, value: str, ex: int) -> None:
        self.set_calls.append((key, value, ex))

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


class FakeRedisClient:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis

    async def init(self) -> FakeRedis:
        return self._redis


def install_llm_slot_recorder(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    class RecordingSlot:
        def __init__(self, attributes: dict | None) -> None:
            self.attributes = attributes or {}

        async def __aenter__(self) -> None:
            calls.append(self.attributes)

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    def fake_llm_concurrency_slot(attributes: dict | None = None):
        return RecordingSlot(attributes)

    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.llm_concurrency_slot",
        fake_llm_concurrency_slot,
    )
    return calls


async def test_stream_error_publishes_error_and_done_and_cleans_lock(
    monkeypatch,
) -> None:
    """Stream LLM failure: error + done published to Redis, idempotency lock cleaned."""
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=_make_streaming_llm(
            [],
            error=app_service_error("provider failed", code="LLM_FAILED"),
        ),
    )

    result = await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        channel="stream:err",
        assistant_message_id=assistant_message_id,
        idempotency_lock_key="idempotency:err",
    )

    assert redis.published == [
        ("stream:err", encode_started_event()),
        ("stream:err", encode_error_event("provider failed")),
        ("stream:err", encode_done_event()),
    ]
    assert redis.deleted == ["idempotency:err"]
    assert result.success is False
    assert result.error == "provider failed"


async def test_stream_done_always_published_even_on_system_error(monkeypatch) -> None:
    """System exception: done event still published (finally guarantee)."""
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=_make_streaming_llm([], error=RuntimeError("secret crash")),
    )

    result = await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        channel="stream:crash",
        assistant_message_id=assistant_message_id,
        idempotency_lock_key="idempotency:crash",
    )

    assert result.success is False
    assert result.error == "服务暂时不可用，请稍后重试"
    done_events = [p for p in redis.published if p[1] == encode_done_event()]
    assert len(done_events) == 1
    assert redis.deleted == ["idempotency:crash"]


async def test_nonstream_idempotency_lock_written_on_success(monkeypatch) -> None:
    """Non-stream success path writes idempotency lock via persistence_handler."""
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    user_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=_make_nonstreaming_llm(
            LLMResultDTO(content="ok", completion_tokens=1)
        ),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda c: 1)

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        assistant_message_id=assistant_message_id,
        user_id=user_id,
        idempotency_lock_key="idempotency:ns",
    )

    assert result.success is True
    assert redis.set_calls == [("idempotency:ns", str(assistant_message_id), 3600)]


async def test_nonstream_idempotency_lock_skipped_when_key_none(monkeypatch) -> None:
    """No idempotency lock written when key is None."""
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=_make_nonstreaming_llm(
            LLMResultDTO(content="ok", completion_tokens=1)
        ),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda c: 1)

    await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        idempotency_lock_key=None,
    )

    assert redis.set_calls == []


async def test_nonstream_failure_cleans_idempotency_lock(monkeypatch) -> None:
    """Non-stream LLM failure: idempotency lock cleaned, message persisted as failed."""
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=_make_nonstreaming_llm(
            LLMResultDTO(content="", success=False, error_message="LLM refused")
        ),
    )

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        assistant_message_id=assistant_message_id,
        idempotency_lock_key="idempotency:fail",
    )

    assert result.success is False
    assert redis.deleted == ["idempotency:fail"]
    uow.chat_repo.update_message_status.assert_awaited_once()
    kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert kwargs["message_metadata"]["response_outcome"] == "failed"


async def test_persistence_handler_write_idempotency_lock() -> None:
    """WorkerPersistenceHandler.write_idempotency_message writes to Redis with TTL."""
    redis = FakeRedis()
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    handler = WorkerPersistenceHandler(uow=uow, redis_client=FakeRedisClient(redis))

    msg_id = uuid.uuid4()
    await handler.write_idempotency_message(
        idempotency_lock_key="lock:abc",
        assistant_message_id=msg_id,
    )

    assert redis.set_calls == [("lock:abc", str(msg_id), 3600)]


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_streaming_llm(chunks: list[str], error: Exception | None = None):
    from collections.abc import AsyncIterator

    from backend.models.schemas.chat.dto import LLMQueryDTO

    class StreamingLLM:
        provider_name = "fake"
        model_name = "fake-model"

        def __init__(self, chunks, error):
            self.chunks = chunks
            self.error = error
            self.generate_response = AsyncMock(
                return_value=LLMResultDTO(content="unused")
            )

        async def stream_response(self, query: LLMQueryDTO) -> AsyncIterator[str]:
            for chunk in self.chunks:
                yield chunk
            if self.error is not None:
                raise self.error

    return StreamingLLM(chunks, error)


def _make_nonstreaming_llm(result: LLMResultDTO):
    class NonStreamingLLM:
        provider_name = "fake"
        model_name = "fake-model"

        def __init__(self, result):
            self.generate_response = AsyncMock(return_value=result)

    return NonStreamingLLM(result)
