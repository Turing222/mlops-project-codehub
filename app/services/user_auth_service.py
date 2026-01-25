from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.models.orm.user import User
from app.models.schemas.user import UserCreate
from app.repositories.user_repo import UserRepository
from app.services.base import BaseService


class User_Auth_Service(BaseService(UserRepository)):
    @staticmethod
    async def get_by_username(session: AsyncSession, username: str) -> User:
        statement = select(User).where(User.username == username)
        result = await session.exec(statement)
        return result.first()

    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> User:
        statement = select(User).where(User.email == email)
        try:
            result = await session.exec(statement)
        except Exception as e:
            # HTTPException
            raise Exception(status_code=400, detail="该邮箱已被注册") from e
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
        user = await User_Auth_Service.get_by_username(session, username)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user
