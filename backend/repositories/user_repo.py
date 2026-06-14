"""User persistence repository.

职责：封装 User 表的查询、创建、更新、批量导入和 Token 原子操作。
边界：本模块不处理密码哈希和认证逻辑，只接收哈希后的持久化字段。
"""

import uuid
from collections.abc import Sequence
from typing import Any, TypedDict

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.user import User
from backend.models.schemas.user_schema import UserUpdate
from backend.repositories.base import CRUDBase


class UserCreateData(TypedDict, total=False):
    """创建用户时所需的持久化字段，不含明文密码。"""

    username: str
    email: str | None
    hashed_password: str | None
    max_tokens: int
    phone: str | None
    auth_provider: str | None
    google_sub: str | None


class UserRepository:
    """用户持久化操作，组合 CRUDBase 并提供 Token 原子操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.crud: CRUDBase[User, BaseModel, UserUpdate] = CRUDBase(User, session)

    async def get(self, id: Any) -> User | None:
        return await self.crud.get(id)

    async def get_multi(self, *, skip: int = 0, limit: int = 100) -> Sequence[User]:
        return await self.crud.get_multi(skip=skip, limit=limit)

    async def create(self, *, obj_in: UserCreateData) -> User:
        create_data: dict[str, Any] = {
            "username": obj_in["username"],
            "email": obj_in.get("email"),
            "hashed_password": obj_in.get("hashed_password"),
            "max_tokens": obj_in.get("max_tokens", 100000),
            "phone": obj_in.get("phone"),
            "auth_provider": obj_in.get("auth_provider"),
            "google_sub": obj_in.get("google_sub"),
        }
        return await self.crud.create(obj_in=create_data)

    async def update(
        self, *, db_obj: User, obj_in: UserUpdate | dict[str, Any]
    ) -> User:
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

    async def get_by_phone(self, phone: str) -> User | None:
        statement = select(User).where(User.phone == phone)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_by_google_sub(self, google_sub: str) -> User | None:
        statement = select(User).where(User.google_sub == google_sub)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_existing_usernames(self, usernames: list[str]) -> set[str]:
        if not usernames:
            return set()

        # 只查 username 列，避免批量导入预检查时把整行用户数据拉进内存。
        stmt = select(User.username).where(User.username.in_(usernames))
        result = await self.session.execute(stmt)

        return set(result.scalars().all())

    async def bulk_upsert(self, user_maps: list[dict[str, str]]) -> None:
        """PostgreSQL INSERT … ON CONFLICT 批量写入，以 email 为冲突键更新 username。"""
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
        """无上限检查的原子 Token 累加，适用于后台统计等非关键路径。

        关键对话路径请使用 try_increment_used_tokens_with_limit。
        """
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(used_tokens=User.used_tokens + amount)
        )
        await self.session.execute(stmt)

    async def get_with_lock(self, user_id: uuid.UUID) -> User | None:
        """SELECT … FOR UPDATE 行锁读取，防止余额校验时的 TOCTOU 竞态。

        必须在已开启事务的 UoW 上下文内调用。
        """
        stmt = select(User).where(User.id == user_id).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def try_increment_used_tokens_with_limit(
        self,
        user_id: uuid.UUID,
        amount: int,
    ) -> bool:
        """带上限检查的条件原子 Token 累加。

        单条 UPDATE … WHERE used_tokens + amount <= max_tokens。
        若返回 None 表示额度不足或用户不存在。与 get_with_lock 配合
        可消除高并发下的 Token 超支问题。
        """
        stmt = (
            update(User)
            .where(
                User.id == user_id,
                User.used_tokens + amount <= User.max_tokens,
            )
            .values(used_tokens=User.used_tokens + amount)
            .returning(User.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
