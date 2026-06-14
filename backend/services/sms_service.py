"""SMS verification code service.

职责：生成、发送、校验短信验证码；管理发送频率限制。
边界：本模块不处理用户查找或 JWT 签发，仅负责验证码的生命周期。
"""

import logging
import secrets
import string
from collections.abc import Sequence
from typing import cast

from backend.core.exceptions import app_bad_request, app_too_many_requests
from backend.infra.redis import RedisClient

logger = logging.getLogger(__name__)

_SMS_CODE_PREFIX = "sms:"
_SMS_RATE_PREFIX = "sms_rate:"
_SMS_VERIFY_FAILURE_PREFIX = "sms_verify_fail:"
_SMS_VERIFY_LOCK_PREFIX = "sms_verify_lock:"

LUA_VERIFY_CODE = """
local code_key = KEYS[1]
local failure_key = KEYS[2]
local lock_key = KEYS[3]
local submitted_code = ARGV[1]
local failure_limit = tonumber(ARGV[2])
local failure_window_seconds = tonumber(ARGV[3])
local lockout_seconds = tonumber(ARGV[4])

if redis.call("GET", lock_key) then
    return {0, "locked", 0}
end

local stored_code = redis.call("GET", code_key)
if not stored_code then
    return {0, "missing", 0}
end

if stored_code == submitted_code then
    redis.call("DEL", code_key, failure_key, lock_key)
    return {1, "ok", 0}
end

if failure_limit <= 0 then
    return {0, "wrong", 0}
end

local failure_count = redis.call("INCR", failure_key)
if failure_count == 1 then
    redis.call("EXPIRE", failure_key, failure_window_seconds)
end

if failure_count >= failure_limit then
    redis.call("SET", lock_key, "1", "EX", lockout_seconds)
    redis.call("DEL", failure_key)
    return {0, "wrong_locked", failure_count}
end

return {0, "wrong", failure_count}
"""


class SMSService:
    """短信验证码服务（mock 模式下验证码仅记录到日志）。"""

    def __init__(
        self,
        redis_client: RedisClient,
        sms_code_expire_seconds: int,
        sms_code_rate_limit_seconds: int,
        sms_mock_mode: bool,
        sms_verify_failure_limit: int = 5,
        sms_verify_failure_window_seconds: int = 300,
        sms_verify_lockout_seconds: int = 600,
    ) -> None:
        self._redis_client = redis_client
        self._sms_code_expire_seconds = sms_code_expire_seconds
        self._sms_code_rate_limit_seconds = sms_code_rate_limit_seconds
        self._sms_mock_mode = sms_mock_mode
        self._sms_verify_failure_limit = sms_verify_failure_limit
        self._sms_verify_failure_window_seconds = sms_verify_failure_window_seconds
        self._sms_verify_lockout_seconds = sms_verify_lockout_seconds

    async def _get_redis(self):
        return await self._redis_client.init()

    async def send_code(self, phone: str) -> str:
        """生成验证码并存入 Redis，mock 模式下仅写日志。

        Returns:
            生成的 6 位验证码。
        """
        redis = await self._get_redis()

        # 频率限制检查
        rate_key = f"{_SMS_RATE_PREFIX}{phone}"
        if await redis.get(rate_key):
            raise app_bad_request("发送过于频繁，请稍后再试", code="SMS_RATE_LIMITED")

        # 生成 6 位随机验证码（Mock 和生产模式统一使用随机码，Mock 模式下验证码仅通过服务端日志可见）
        code = "".join(secrets.choice(string.digits) for _ in range(6))

        # 存入 Redis（TTL 由配置决定）
        code_key = f"{_SMS_CODE_PREFIX}{phone}"
        await redis.set(code_key, code, ex=self._sms_code_expire_seconds)

        # 设置发送间隔限制
        await redis.set(rate_key, "1", ex=self._sms_code_rate_limit_seconds)

        # Mock 模式：记录日志
        if self._sms_mock_mode:
            logger.info("[SMS Mock] 验证码 phone=%s code=%s", phone, code)
        else:
            # TODO: 对接真实 SMS 服务商（阿里云/腾讯云）
            logger.info("[SMS] 验证码已发送至 phone=%s", phone)

        return code

    async def verify_code(self, phone: str, code: str) -> bool:
        """校验验证码，成功后删除（一次性使用）。

        Returns:
            True 表示验证通过，False 表示验证码错误或已过期。
        """
        redis = await self._get_redis()
        code_key = f"{_SMS_CODE_PREFIX}{phone}"
        failure_key = f"{_SMS_VERIFY_FAILURE_PREFIX}{phone}"
        lock_key = f"{_SMS_VERIFY_LOCK_PREFIX}{phone}"

        eval_result = cast(
            Sequence[object],
            await redis.eval(
                LUA_VERIFY_CODE,
                3,
                code_key,
                failure_key,
                lock_key,
                code,
                self._sms_verify_failure_limit,
                self._sms_verify_failure_window_seconds,
                self._sms_verify_lockout_seconds,
            ),
        )
        is_valid = bool(self._decode_eval_int(eval_result[0]))
        status = self._decode_eval_status(eval_result[1])

        if status in {"locked", "wrong_locked"}:
            raise app_too_many_requests(
                "验证码尝试过于频繁，请稍后再试",
                code="SMS_VERIFY_LOCKED",
                details={"lockout_seconds": self._sms_verify_lockout_seconds},
            )

        return is_valid

    @staticmethod
    def _decode_eval_status(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode()
        return str(value)

    @staticmethod
    def _decode_eval_int(value: object) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, bytes):
            return int(value.decode())
        if isinstance(value, str):
            return int(value)
        raise TypeError(f"Unexpected Redis eval integer value: {value!r}")
