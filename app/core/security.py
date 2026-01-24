from datetime import datetime, timedelta
from typing import Any

from fastapi.concurrency import run_in_threadpool
from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """异步校验密码：防止计算阻塞事件循环"""

    # 使用 run_in_executor 在线程池中执行耗时的哈希计算
    return await run_in_threadpool(pwd_context.verify, plain_password, hashed_password)


async def get_password_hash(password: str) -> str:
    """异步生成哈希密码"""

    return await run_in_threadpool(pwd_context.hash, password)


def create_access_token(subject: str | Any, expires_delta: timedelta = None) -> str:
    """
    生成 JWT Token：这个操作非常快，通常保持同步即可。
    注意：修正了原代码中 datetime() 的调用错误
    """
    if expires_delta:
        expire = datetime.now() + expires_delta
    else:
        expire = datetime.now() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt
