import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.user import User  # 你的 SQLAlchemy 模型
from backend.models.schemas.user_schema import UserCreate, UserUpdate
from backend.repositories.base import CRUDBase


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.crud: CRUDBase[User, UserCreate, UserUpdate] = CRUDBase(User, session)

    async def get(self, id: Any) -> User | None:
        return await self.crud.get(id)

    async def get_multi(self, *, skip: int = 0, limit: int = 100) -> Sequence[User] | None:
        return await self.crud.get_multi(skip=skip, limit=limit)

    async def create(self, *, obj_in: UserCreate | dict[str, Any]) -> User:
        return await self.crud.create(obj_in=obj_in)

    async def update(self, *, db_obj: User, obj_in: UserUpdate | dict[str, Any]) -> User:
        return await self.crud.update(db_obj=db_obj, obj_in=obj_in)

    async def remove(self, *, id: Any) -> User | None:
        return await self.crud.remove(id=id)

    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_by_username(self, username: str) -> User | None:
        statement = select(User).where(User.username == username)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_existing_usernames(self, usernames: list[str]) -> set[str]:
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

    async def bulk_upsert(self, user_maps: list[dict[str, str]]) -> None:
        """
        执行 Postgres 专用的 upsert 逻辑
        """
        required_keys = {"username", "email", "hashed_password"}
        normalized_rows: list[dict[str, str]] = []
        for idx, row in enumerate(user_maps):
            missing = required_keys.difference(row.keys())
            if missing:
                missing_text = ", ".join(sorted(missing))
                raise ValueError(f"row {idx} is missing required keys: {missing_text}")
            normalized_rows.append(
                {
                    "username": row["username"],
                    "email": row["email"],
                    "hashed_password": row["hashed_password"],
                }
            )

        stmt = pg_insert(User).values(normalized_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["email"], set_={"username": stmt.excluded.username}
        )
        await self.session.execute(stmt)

    async def increment_used_tokens(self, user_id: uuid.UUID, amount: int) -> None:
        """
        原子增加用户的已用 Token 数。
        使用 SQL 级别的原子操作 (SET used_tokens = used_tokens + amount)，
        避免并发下的「读-改-写」丢失更新问题。

        注意：此方法不做上限检查，适用于非关键路径（如后台统计）。
        关键对话路径请使用 increment_used_tokens_guarded。
        """
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(used_tokens=User.used_tokens + amount)
        )
        await self.session.execute(stmt)

    async def get_with_lock(self, user_id: uuid.UUID) -> User | None:
        """
        SELECT FOR UPDATE 读取用户行，锁定直到当前事务结束。

        用于余额检查前的悲观锁读，防止多个并发请求同时通过余额校验（TOCTOU）。
        必须在已开启事务的 UoW 上下文内调用（即 async with uow 块中）。
        """
        from sqlalchemy import select

        stmt = select(User).where(User.id == user_id).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def increment_used_tokens_guarded(
        self,
        user_id: uuid.UUID,
        amount: int,
    ) -> bool:
        """
        带上限检查的条件原子 Token 累加（R1 + R5 修复）。

        实现：单条 UPDATE WHERE used_tokens + amount <= max_tokens
        - 若更新成功（rowcount == 1）：返回 True
        - 若已超出上限（rowcount == 0）：返回 False，调用方应记录并告知用户

        此方法是原子的，不存在读-改-写竞态，与 get_with_lock 配合可彻底
        消除高并发下的 Token 超支问题。
        """
        from sqlalchemy import func

        stmt = (
            update(User)
            .where(
                User.id == user_id,
                User.used_tokens + amount <= User.max_tokens,
            )
            .values(used_tokens=User.used_tokens + amount)
            .returning(func.count())
        )
        result = await self.session.execute(stmt)
        # rowcount 在 asyncpg UPDATE + RETURNING 场景下是实际受影响行数
        # ty 对 SQLAlchemy CursorResult 类型推断不完整，此处 ignore 是已知误报
        return result.rowcount > 0  # type: ignore[union-attr]
