# %%
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.models.user import User  # 你的 SQLAlchemy 模型


# %%
class UserRepository:
    def __init__(self, session):
        self.session = session
        # %%

    async def get_users(self, skip: int = 0, limit: int = 10, username: str = None):
        """
        查询用户 默认不跳过 默认上限10条
        使用 Core 风格，性能高。
        """
        # %%
        statement = select(User).offset(skip).limit(limit)
        if username:
            # 增加过滤条件
            statement = statement.where(User.username == username)
        # %%

        result = await self.session.execute(statement)
        return result.scalars().all()

    # %%
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
