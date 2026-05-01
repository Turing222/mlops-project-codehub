from __future__ import annotations

import redis.asyncio as redis

from backend.config.settings import settings
from backend.infra.task_broker import broker


@broker.task(task_name="integration_echo")
async def integration_echo_task(result_key: str, value: str) -> str:
    """Tiny TaskIQ task used to prove Redis enqueue + worker consumption."""
    client = redis.from_url(settings.taskiq_redis_url, decode_responses=True)
    try:
        await client.set(result_key, value, ex=60)
    finally:
        await client.aclose()
    return value
