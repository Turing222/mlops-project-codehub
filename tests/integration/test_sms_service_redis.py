"""SMS verification Redis integration tests.

职责：在真实 Redis 上验证 Lua 状态机的计数、锁定、清理和单次消费；边界：不调用 HTTP endpoint；副作用：创建并清理随机测试 key。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import redis.asyncio as redis

from backend.core.exceptions import AppException
from backend.infra.redis import RedisClient
from backend.services.sms_service import SMSService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_redis,
    pytest.mark.asyncio,
]


async def test_sms_verify_lua_state_machine() -> None:
    redis_connection = redis.from_url(
        os.environ["TEST_REDIS_URL"],
        decode_responses=True,
    )
    redis_client = RedisClient()
    redis_client.client = redis_connection
    phone = f"test-{uuid.uuid4().hex}"
    code_key = f"sms:{phone}"
    failure_key = f"sms_verify_fail:{phone}"
    lock_key = f"sms_verify_lock:{phone}"
    service = SMSService(
        redis_client=redis_client,
        sms_code_expire_seconds=60,
        sms_code_rate_limit_seconds=60,
        sms_mock_mode=False,
        sms_verify_failure_limit=2,
        sms_verify_failure_window_seconds=30,
        sms_verify_lockout_seconds=60,
    )

    try:
        assert await service.verify_code(phone, "000000") is False
        assert await redis_connection.get(failure_key) is None

        await redis_connection.set(code_key, "123456", ex=60)
        assert await service.verify_code(phone, "000000") is False
        assert await redis_connection.get(failure_key) == "1"
        assert await redis_connection.ttl(failure_key) > 0

        with pytest.raises(AppException) as exc_info:
            await service.verify_code(phone, "000000")
        assert exc_info.value.code == "SMS_VERIFY_LOCKED"
        assert await redis_connection.get(lock_key) == "1"

        await redis_connection.delete(code_key, failure_key, lock_key)
        await redis_connection.set(code_key, "123456", ex=60)
        await redis_connection.set(failure_key, "1", ex=30)
        assert await service.verify_code(phone, "123456") is True
        assert await redis_connection.mget(code_key, failure_key, lock_key) == [
            None,
            None,
            None,
        ]

        await redis_connection.set(code_key, "123456", ex=60)
        results = await asyncio.gather(
            service.verify_code(phone, "123456"),
            service.verify_code(phone, "123456"),
        )
        assert sorted(results) == [False, True]
    finally:
        await redis_connection.delete(code_key, failure_key, lock_key)
        await redis_connection.aclose()
