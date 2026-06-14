"""WorkerStreamPublisher unit tests — chunk, error, done event publishing.

职责：验证 WorkerStreamPublisher 正确编码并发布 chunk、error、done 事件到 Redis channel；
边界：使用 FakeRedis，不连接真实 Redis；副作用：无。
"""

import pytest

from backend.application.chat.stream_events import (
    encode_chunk_event,
    encode_done_event,
    encode_error_event,
    encode_started_event,
)
from backend.application.chat.worker_stream_publisher import WorkerStreamPublisher

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))


class FakeRedisClient:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis

    async def init(self) -> FakeRedis:
        return self._redis


async def test_publish_chunk_encodes_and_sends() -> None:
    redis = FakeRedis()
    publisher = WorkerStreamPublisher(redis_client=FakeRedisClient(redis))

    await publisher.publish_chunk("stream:test", "hello")

    assert redis.published == [("stream:test", encode_chunk_event("hello"))]


async def test_publish_error_encodes_and_sends() -> None:
    redis = FakeRedis()
    publisher = WorkerStreamPublisher(redis_client=FakeRedisClient(redis))

    await publisher.publish_error("stream:err", "something failed")

    assert redis.published == [("stream:err", encode_error_event("something failed"))]


async def test_publish_done_encodes_and_sends() -> None:
    redis = FakeRedis()
    publisher = WorkerStreamPublisher(redis_client=FakeRedisClient(redis))

    await publisher.publish_done("stream:done")

    assert redis.published == [("stream:done", encode_done_event())]


async def test_publish_started_encodes_and_sends() -> None:
    redis = FakeRedis()
    publisher = WorkerStreamPublisher(redis_client=FakeRedisClient(redis))

    await publisher.publish_started("stream:started")

    assert redis.published == [("stream:started", encode_started_event())]


async def test_multiple_publishes_on_same_channel() -> None:
    redis = FakeRedis()
    publisher = WorkerStreamPublisher(redis_client=FakeRedisClient(redis))

    await publisher.publish_chunk("stream:s", "chunk1")
    await publisher.publish_chunk("stream:s", "chunk2")
    await publisher.publish_done("stream:s")

    assert redis.published == [
        ("stream:s", encode_chunk_event("chunk1")),
        ("stream:s", encode_chunk_event("chunk2")),
        ("stream:s", encode_done_event()),
    ]


async def test_redis_connection_reused_across_calls() -> None:
    redis = FakeRedis()
    client = FakeRedisClient(redis)
    init_call_count = 0
    original_init = client.init

    async def counting_init():
        nonlocal init_call_count
        init_call_count += 1
        return await original_init()

    client.init = counting_init

    publisher = WorkerStreamPublisher(redis_client=client)

    await publisher.publish_chunk("ch", "a")
    await publisher.publish_done("ch")

    assert init_call_count == 2
