from typing import Optional

from app.models.user import User
from app.schemas.user import UserCreate
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_password_hash, verify_password


class UserService:
    @staticmethod
    async def get_by_username(session: AsyncSession, username: str) -> User:
        statement = select(User).where(User.username == username)
        result = await session.exec(statement)
        return result.first()

    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> User:
        statement = select(User).where(User.email == email)
        result = await session.exec(statement)
        return result.first()

    @staticmethod
    async def create(session: AsyncSession, user_in: UserCreate) -> User:
        """创建用户"""
        # 1. 转换为 DB 模型
        db_obj = User.model_validate(
            user_in, update={"hashed_password": get_password_hash(user_in.password)}
        )
        # 2. 写入数据库
        session.add(db_obj)
        await session.commit()
        await session.refresh(db_obj)
        return db_obj

    @staticmethod
    async def authenticate(session: AsyncSession, username: str, password: str) -> User:
        """验证用户名和密码"""
        user = await UserService.get_by_username(session, username)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user
