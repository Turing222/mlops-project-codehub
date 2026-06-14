from __future__ import annotations

import redis.asyncio as redis
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from backend.config.settings import settings

# Separate queue so the test worker never competes with the Docker
# task_worker (which listens on the default "taskiq" queue).
_TEST_QUEUE_NAME = "taskiq_test"

_TEST_BROKER = ListQueueBroker(
    url=settings.taskiq_redis_url,
    queue_name=_TEST_QUEUE_NAME,
).with_result_backend(
    RedisAsyncResultBackend(redis_url=settings.taskiq_redis_url),
)


@_TEST_BROKER.task(task_name="integration_echo")
async def integration_echo_task(result_key: str, value: str) -> str:
    """Tiny TaskIQ task used to prove Redis enqueue + worker consumption."""
    client = redis.from_url(settings.taskiq_redis_url, decode_responses=True)
    try:
        await client.set(result_key, value, ex=60)
    finally:
        await client.aclose()
    return value
