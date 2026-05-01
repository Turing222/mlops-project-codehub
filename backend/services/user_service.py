"""User service.

职责：封装用户注册、认证、更新、删除和个人工作区创建。
边界：本模块不签发 token、不处理 HTTP 响应；认证接口只返回匹配的用户对象。
风险：注册前检查不能替代数据库唯一约束，并发冲突仍需捕获 IntegrityError。
"""

import logging
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import (
    app_not_found,
    app_validation_error,
)
from backend.core.security import get_password_hash, verify_password
from backend.models.orm.access import WorkspaceRole
from backend.models.orm.user import User
from backend.models.schemas.user_schema import (
    UserCreate,
    UserLogin,
    UserUpdate,
)
from backend.services.base import BaseService

logger = logging.getLogger(__name__)


class UserService(BaseService[AbstractUnitOfWork]):
    """用户账号相关业务服务。"""

    def __init__(self, uow: AbstractUnitOfWork) -> None:
        super().__init__(uow)

    async def get_by_id(self, id: Any) -> User | None:
        """按 id 读取用户。"""

        user = await self.uow.user_repo.get(id)
        return user

    async def get_by_email(self, email: EmailStr) -> User | None:
        """按邮箱读取用户。"""

        user = await self.uow.user_repo.get_by_email(email)
        return user

    async def get_by_username(self, username: str) -> User | None:
        """按用户名读取用户。"""

        user = await self.uow.user_repo.get_by_username(username)
        return user

    async def user_register(self, user_in: UserCreate) -> User | None:
        """注册用户，并把唯一约束冲突转换为业务错误。"""
        logger.debug(
            "注册请求: username=%s, email=%s",
            user_in.username,
            user_in.email,
        )

        if await self.uow.user_repo.get_by_email(email=user_in.email):
            raise app_validation_error(
                "该邮箱已被注册", code="EMAIL_ALREADY_REGISTERED"
            )
        if await self.uow.user_repo.get_by_username(username=user_in.username):
            raise app_validation_error(
                "该用户名已被注册",
                code="USERNAME_ALREADY_REGISTERED",
            )

        # 明文密码只在 service 内短暂停留，入库前必须替换为哈希。
        obj_in_data = user_in.model_dump()
        obj_in_data.pop("password")
        obj_in_data.pop("confirm_password")
        obj_in_data["hashed_password"] = await get_password_hash(user_in.password)

        try:
            user = await self.uow.user_repo.create(obj_in=obj_in_data)
        except IntegrityError as exc:
            # 并发注册仍可能越过预检查，数据库唯一约束是最终防线。
            raise app_validation_error(
                "用户名或邮箱已被注册",
                code="USER_ALREADY_REGISTERED",
            ) from exc

        return user

    async def user_register_with_personal_workspace(
        self, user_in: UserCreate
    ) -> User | None:
        user = await self.user_register(user_in)
        if not user:
            return None

        await self._create_personal_workspace_for_user(user)
        return user

    async def _create_personal_workspace_for_user(self, user: User) -> None:
        workspace_slug = f"{user.username}-{user.id.hex[:8]}"
        workspace = await self.uow.access_repo.create_workspace(
            name=f"{user.username}'s Workspace",
            slug=workspace_slug,
            owner_id=user.id,
        )
        await self.uow.access_repo.add_workspace_role(
            user_id=user.id,
            workspace_id=workspace.id,
            role=WorkspaceRole.OWNER,
        )

    async def user_update(self, user_id: uuid.UUID, user_in: UserUpdate) -> User | None:
        """更新用户基础信息。"""
        db_obj = await self.uow.user_repo.get(id=user_id)
        if not db_obj:
            raise app_not_found("用户不存在", code="USER_NOT_FOUND")

        user = await self.uow.user_repo.update(db_obj=db_obj, obj_in=user_in)
        return user

    async def authenticate(self, user_in: UserLogin) -> User | None:
        """验证用户名和密码，失败时返回 None。"""

        user = await self.uow.user_repo.get_by_username(user_in.username)
        if not user:
            return None
        if not await verify_password(user_in.password, user.hashed_password):
            return None
        return user

    async def get_multi(self, skip: int = 0, limit: int = 100) -> Sequence[User] | None:
        users = await self.uow.user_repo.get_multi(skip=skip, limit=limit)
        return users

    async def delete(self, id: int) -> User | None:
        user = await self.uow.user_repo.remove(id=id)
        return user
