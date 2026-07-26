"""Real Redis contract for Chat recovery dispatch.

职责：验证 fire-and-forget recovery payload 以稳定 task identity 写入真实 Redis。
边界：不启动 Worker、不调用 LLM；使用独立测试队列并在结束时清理；副作用：短暂写 Redis。
"""

from __future__ import annotations

import uuid

import pytest
import redis.asyncio as redis

from backend.infra import task_dispatcher as dispatcher_module
from backend.infra.task_broker import broker
from backend.infra.task_dispatcher import TASK_STREAM, TaskDispatcher
from backend.models.schemas.chat.payloads import (
    GenerationAttemptPayload,
    GenerationDispatchContext,
    GenerationPayload,
)
from tests.helpers.env import require_env

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_redis,
    pytest.mark.requires_taskiq,
]


async def test_recovery_dispatch_roundtrips_through_real_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_name = f"taskiq_chat_recovery_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(dispatcher_module, "TASKIQ_QUEUE_NAME", queue_name)
    redis_connection = redis.from_url(
        require_env("TEST_TASKIQ_REDIS_URL"),
        decode_responses=False,
    )
    attempt = GenerationAttemptPayload(
        request_id=uuid.uuid4(),
        attempt=2,
        task_id=f"recovery-{uuid.uuid4().hex}",
        lease_token=uuid.uuid4().hex,
    )
    context = GenerationDispatchContext(
        mode="stream",
        generation_payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="recover through redis",
        ),
    )
    try:
        await TaskDispatcher(redis_connection).enqueue_generation_recovery(
            dispatch_context=context,
            assistant_message_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            generation_attempt=attempt,
        )

        raw_message = await redis_connection.rpop(queue_name)
        assert raw_message is not None
        parsed = broker.formatter.loads(raw_message)
        assert parsed.task_id == attempt.task_id
        assert parsed.task_name == TASK_STREAM
        assert parsed.args[0]["generation_attempt"] == attempt.model_dump(mode="json")
        assert parsed.args[0]["channel"] == f"stream:{attempt.task_id}"
    finally:
        await redis_connection.delete(queue_name)
        await redis_connection.aclose()
