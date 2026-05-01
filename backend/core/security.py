"""Password and JWT helpers.

职责：封装密码哈希校验和访问令牌生成。
边界：本模块不做用户查询或权限判断；只处理加密/签名 primitives。
副作用：CPU 密集的密码操作放入线程池，避免阻塞事件循环。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi.concurrency import run_in_threadpool
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

from backend.config.settings import settings

password_hasher = PasswordHash.recommended()


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """在线程池中校验密码，避免阻塞事件循环。"""
    try:
        return await run_in_threadpool(
            password_hasher.verify, plain_password, hashed_password
        )
    except PwdlibError:
        # 非法哈希按认证失败处理，避免把内部格式错误暴露给调用方。
        return False


async def get_password_hash(password: str) -> str:
    """在线程池中生成密码哈希。"""

    return await run_in_threadpool(password_hasher.hash, password)


def create_access_token(
    subject: str | Any, expires_delta: timedelta | None = None
) -> str:
    """生成带 UTC 时间戳的访问令牌。"""
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    # 使用 timezone-aware datetime，避免不同服务器本地时区影响 token 语义。
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "iat": now,
    }

    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt
