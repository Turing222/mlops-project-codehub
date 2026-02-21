from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi.concurrency import run_in_threadpool
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

from backend.core.config import settings

password_hasher = PasswordHash.recommended()


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    异步校验密码：防止计算阻塞事件循环。
    Argon2 相比 Bcrypt 更消耗 CPU/内存，因此 run_in_threadpool 是必须的。
    """
    try:
        return await run_in_threadpool(
            password_hasher.verify, plain_password, hashed_password
        )
    except PwdlibError:
        # 处理可能的解码错误或非法哈希格式
        return False


async def get_password_hash(password: str) -> str:
    """异步生成哈希密码"""

    return await run_in_threadpool(password_hasher.verify.hash, password)


def create_access_token(
    subject: str | Any, expires_delta: timedelta | None = None
) -> str:
    """
    生成 JWT Token。
    注意：2026 年标准必须显式使用 timezone.utc，避免服务器系统时间偏差。
    """
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    # PyJWT 要求 exp 是 UTC 时间戳或 datetime 对象
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "iat": now,  # 建议加上 Issued At 时间，方便审计
    }

    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt
