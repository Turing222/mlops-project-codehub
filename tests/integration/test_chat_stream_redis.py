"""Real Redis transport contract for Chat worker stream events.

职责：验证 retry 错误字段经过真实 Redis pub/sub 后保持结构化；
边界：不启动 Worker 或 HTTP stack，只创建并清理随机 channel；副作用：临时订阅 Redis。
"""

from __future__ import annotations

import os
import uuid

import pytest
import redis.asyncio as redis

from backend.application.chat.stream_events import decode_stream_event
from backend.application.chat.worker_stream_publisher import WorkerStreamPublisher
from backend.infra.redis import RedisClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_redis,
]


async def test_chat_retry_error_contract_survives_real_redis_pubsub() -> None:
    redis_connection = redis.from_url(
        os.environ["TEST_REDIS_URL"],
        decode_responses=True,
    )
    redis_client = RedisClient()
    redis_client.client = redis_connection
    publisher = WorkerStreamPublisher(redis_client=redis_client)
    pubsub = redis_connection.pubsub()
    channel = f"chat:ws6:{uuid.uuid4().hex}"

    try:
        await pubsub.subscribe(channel)
        subscription = await pubsub.get_message(
            ignore_subscribe_messages=False,
            timeout=2,
        )
        assert subscription is not None
        assert subscription["type"] == "subscribe"

        await publisher.publish_started(channel)
        await publisher.publish_error(
            channel,
            "generation failed",
            error_code="CHAT_GENERATION_FAILED",
            retryable=True,
        )
        await publisher.publish_done(channel)

        events = []
        while len(events) < 3:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=2,
            )
            assert message is not None
            events.append(decode_stream_event(message["data"]))

        assert events == [
            {"type": "started"},
            {
                "type": "error",
                "message": "generation failed",
                "error_code": "CHAT_GENERATION_FAILED",
                "retryable": True,
            },
            {"type": "done"},
        ]
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis_connection.aclose()
