from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.user import User  # 你的 SQLAlchemy 模型
from app.models.schemas.user import UserCreate, UserUpdate
from app.repositories.base import CRUDBase


class UserRepository(CRUDBase[User, UserCreate, UserUpdate]):
    def __init__(self, session: AsyncSession):
        # 1. 调用父类 CRUDBase 的构造函数，告诉它操作的是 User 模型
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> User | None:
        statement = select(self.model).where(self.model.email == email)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_by_username(self, username: str) -> User | None:
        statement = select(self.model).where(self.model.username == username)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_existing_usernames(self, usernames: list[str]) -> list[str]:
        """
        输入一个用户名列表，返回数据库中已经存在的用户名集合。
        使用 Core 风格，性能高。
        """
        if not usernames:
            return set()

        # 这里的 select(User.username) 就是 Core 风格
        # 它只查询 username 字段，不会把整行数据都查出来
        stmt = select(User.username).where(User.username.in_(usernames))
        result = await self.session.execute(stmt)

        # scalars().all() 会返回一个列表 ['zhangsan', 'lisi', ...]
        # 转成 set 方便后续 O(1) 复杂度的查找比对
        return set(result.scalars().all())

    async def bulk_upsert(self, user_maps: list[dict]):
        """
        执行 Postgres 专用的 upsert 逻辑
        """
        stmt = pg_insert(User).values(user_maps)
        stmt = stmt.on_conflict_do_update(
            index_elements=["email"], set_={"username": stmt.excluded.username}
        )
        await self.session.execute(stmt)
