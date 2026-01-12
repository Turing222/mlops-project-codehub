# app/api/dependencies.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session  # 假设这是你获取 session 的地方
from app.repositories.user_repo import UserRepository


# 1. 这里的逻辑只负责：拿连接 -> 实例化 Repo
def get_user_repo(session: AsyncSession = Depends(get_session)) -> UserRepository:
    return UserRepository(session)