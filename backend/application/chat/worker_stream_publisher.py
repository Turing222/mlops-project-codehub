"""Worker-side Redis stream publisher.

职责：封装 worker 向 Redis channel 发布流式事件的逻辑。
边界：本模块只负责 encode + publish，不做持久化、幂等锁写入或 LLM 编排。
"""

import logging

from backend.application.chat.stream_events import (
    encode_chunk_event,
    encode_done_event,
    encode_error_event,
    encode_started_event,
)
from backend.infra.redis import RedisClient

logger = logging.getLogger(__name__)


class WorkerStreamPublisher:
    """Publish stream events to Redis channels."""

    def __init__(self, *, redis_client: RedisClient) -> None:
        self._redis_client = redis_client

    async def _redis(self):
        return await self._redis_client.init()

    async def publish_chunk(self, channel: str, content: str) -> None:
        redis_connection = await self._redis()
        await redis_connection.publish(channel, encode_chunk_event(content))

    async def publish_started(self, channel: str) -> None:
        redis_connection = await self._redis()
        await redis_connection.publish(channel, encode_started_event())

    async def publish_error(self, channel: str, message: str) -> None:
        redis_connection = await self._redis()
        await redis_connection.publish(channel, encode_error_event(message))

    async def publish_done(self, channel: str) -> None:
        redis_connection = await self._redis()
        await redis_connection.publish(channel, encode_done_event())
