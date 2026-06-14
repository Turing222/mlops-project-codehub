"""Task dispatcher unit tests.

职责：验证 TaskIQ Redis 消息构造、结果读取和错误映射；边界：使用 fake Redis 和 pickle payload，不连接真实 broker；副作用：无。
"""

import json
import pickle
import uuid
from unittest.mock import AsyncMock

import pytest

from backend.infra.task_dispatcher import (
    TASK_INGESTION,
    TASK_NONSTREAM,
    TASK_REPO_ANALYSIS,
    TASK_STREAM,
)


class FakeRedis:
    def __init__(self, result_payload: bytes | None = None) -> None:
        self.lpush = AsyncMock()
        self.get = AsyncMock(return_value=result_payload)
        self.aclose = AsyncMock()


def _decode_lpush_message(redis_client: FakeRedis) -> dict[str, object]:
    _, message = redis_client.lpush.await_args.args
    return json.loads(message.decode())


@pytest.mark.asyncio
async def test_enqueue_stream_passes_params_through() -> None:
    from backend.infra.task_dispatcher import TaskDispatcher

    redis_client = FakeRedis()
    dispatcher = TaskDispatcher(redis_client)
    payload = {"session_id": str(uuid.uuid4()), "query_text": "hello"}
    channel = "stream:test"
    trace_ctx = {"traceparent": "00-test"}
    msg_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    lock_key = "lock:test"

    await dispatcher.enqueue_stream(
        generation_payload=payload,
        channel=channel,
        trace_context=trace_ctx,
        assistant_message_id=msg_id,
        user_id=user_id,
        idempotency_lock_key=lock_key,
    )

    message = _decode_lpush_message(redis_client)
    assert message["task_name"] == TASK_STREAM
    args = message["args"]
    assert len(args) == 1
    assert args[0]["generation_payload"] == payload
    assert args[0]["channel"] == channel
    assert args[0]["trace_context"] == trace_ctx
    assert args[0]["assistant_message_id"] == msg_id
    assert args[0]["user_id"] == user_id
    assert args[0]["idempotency_lock_key"] == lock_key


@pytest.mark.asyncio
async def test_enqueue_nonstream_passes_params_and_returns_result() -> None:
    from backend.infra.task_dispatcher import TaskDispatcher
    from backend.models.schemas.chat.payloads import GenerationResult

    expected_result = {"success": True, "content": "answer"}

    raw_result = pickle.dumps(
        {
            "is_err": False,
            "log": None,
            "return_value": expected_result,
            "execution_time": 0.1,
            "labels": {},
            "error": None,
        }
    )
    redis_client = FakeRedis(result_payload=raw_result)
    dispatcher = TaskDispatcher(redis_client)
    payload = {"session_id": str(uuid.uuid4()), "query_text": "hello"}
    trace_ctx = {"traceparent": "00-test"}
    msg_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    lock_key = "lock:test"

    result = await dispatcher.enqueue_nonstream(
        generation_payload=payload,
        trace_context=trace_ctx,
        assistant_message_id=msg_id,
        user_id=user_id,
        idempotency_lock_key=lock_key,
    )

    message = _decode_lpush_message(redis_client)
    assert message["task_name"] == TASK_NONSTREAM
    args = message["args"]
    assert len(args) == 1
    assert args[0]["generation_payload"] == payload
    assert args[0]["channel"] is None
    assert args[0]["trace_context"] == trace_ctx
    assert args[0]["assistant_message_id"] == msg_id
    assert args[0]["user_id"] == user_id
    assert args[0]["idempotency_lock_key"] == lock_key
    redis_client.get.assert_awaited_once_with(message["task_id"])
    assert isinstance(result, GenerationResult)
    assert result.success is True
    assert result.content == "answer"


@pytest.mark.asyncio
async def test_enqueue_ingestion_passes_params_through() -> None:
    from backend.infra.task_dispatcher import TaskDispatcher

    redis_client = FakeRedis()
    dispatcher = TaskDispatcher(redis_client)
    file_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    trace_ctx = {"traceparent": "00-test"}

    await dispatcher.enqueue_ingestion(
        file_id=file_id,
        task_id=task_id,
        trace_context=trace_ctx,
    )

    message = _decode_lpush_message(redis_client)
    assert message["task_name"] == TASK_INGESTION
    assert message["args"] == [file_id, task_id, trace_ctx]


@pytest.mark.asyncio
async def test_enqueue_repo_analysis_passes_params_through() -> None:
    from backend.infra.task_dispatcher import TaskDispatcher

    redis_client = FakeRedis()
    dispatcher = TaskDispatcher(redis_client)
    run_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    trace_ctx = {"traceparent": "00-test"}

    await dispatcher.enqueue_repo_analysis(
        run_id=run_id,
        task_id=task_id,
        trace_context=trace_ctx,
    )

    message = _decode_lpush_message(redis_client)
    assert message["task_name"] == TASK_REPO_ANALYSIS
    assert message["args"] == [run_id, task_id, trace_ctx]


@pytest.mark.asyncio
async def test_wait_result_timeout_raises_timeout_error() -> None:
    from backend.infra.task_dispatcher import TaskDispatcher

    redis_client = FakeRedis()  # get() returns None by default
    dispatcher = TaskDispatcher(redis_client)

    with pytest.raises(TimeoutError, match="TaskIQ task result timed out"):
        await dispatcher._wait_result("test-task-id", timeout=0.2)


@pytest.mark.asyncio
async def test_wait_result_is_err_raises_runtime_error() -> None:
    from backend.infra.task_dispatcher import TaskDispatcher

    raw_result = pickle.dumps(
        {
            "is_err": True,
            "log": None,
            "return_value": None,
            "execution_time": 0.1,
            "labels": {},
            "error": "task execution failed",
        }
    )
    redis_client = FakeRedis(result_payload=raw_result)
    dispatcher = TaskDispatcher(redis_client)

    with pytest.raises(RuntimeError, match="TaskIQ task failed"):
        await dispatcher._wait_result("test-task-id", timeout=10)


@pytest.mark.asyncio
async def test_send_task_redis_push_error_propagates() -> None:
    from backend.infra.task_dispatcher import TaskDispatcher

    redis_client = FakeRedis()
    redis_client.lpush.side_effect = ConnectionError("Redis unreachable")
    dispatcher = TaskDispatcher(redis_client)

    with pytest.raises(ConnectionError, match="Redis unreachable"):
        await dispatcher._send_task("test_task", "arg1")


@pytest.mark.asyncio
async def test_task_name_constants_match_expected() -> None:
    """Ensure task name constants are not accidentally changed."""
    assert TASK_STREAM == "generate_llm_stream"
    assert TASK_NONSTREAM == "generate_llm_nonstream"
    assert TASK_INGESTION == "ingest_knowledge_file"
    assert TASK_REPO_ANALYSIS == "analyze_repo_readme"


def test_build_taskiq_message_is_loadable_by_worker_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("taskiq")
    monkeypatch.setenv("DEBUG", "false")

    from backend.infra.task_broker import broker
    from backend.infra.task_dispatcher import TaskDispatcher

    payload = {"session_id": str(uuid.uuid4()), "query_text": "hello"}
    raw_message = TaskDispatcher._build_taskiq_message(
        task_id="contract-test-task",
        task_name=TASK_INGESTION,
        args=(payload, "task-id", {"traceparent": "00-test"}),
    )

    parsed = broker.formatter.loads(raw_message)

    assert parsed.task_id == "contract-test-task"
    assert parsed.task_name == TASK_INGESTION
    assert parsed.labels == {}
    assert parsed.labels_types == {}
    assert parsed.args == [payload, "task-id", {"traceparent": "00-test"}]
    assert parsed.kwargs == {}


def test_build_taskiq_message_includes_version_2() -> None:
    from backend.infra.task_dispatcher import TaskDispatcher

    raw_message = TaskDispatcher._build_taskiq_message(
        task_id="version-test",
        task_name="test_task",
        args=("arg1",),
    )
    message = json.loads(raw_message.decode())
    assert message["version"] == 2


def test_llm_task_payload_forbids_extra_fields() -> None:
    import pytest
    from pydantic import ValidationError

    from backend.models.schemas.chat.payloads import LLMTaskPayload

    with pytest.raises(ValidationError, match="extra"):
        LLMTaskPayload(
            generation_payload={"session_id": "test", "query_text": "hi"},
            unexpected_field="bad",
        )
