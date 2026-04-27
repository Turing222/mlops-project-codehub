import logging
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError

from backend.core.exceptions import (
    ResourceNotFound,
    ValidationError,
)
from backend.core.security import get_password_hash, verify_password
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.access import WorkspaceRole
from backend.models.orm.user import User
from backend.models.schemas.user_schema import (
    UserCreate,
    UserLogin,
    UserUpdate,
)
from backend.services.base import BaseService

# 模块级 logger，或者放在类里也可以
logger = logging.getLogger(__name__)


class UserService(BaseService[AbstractUnitOfWork]):
    def __init__(self, uow: AbstractUnitOfWork):
        super().__init__(uow)

    # --- 简单透传逻辑 (Proxy) ---
    async def get_by_id(self, id: Any) -> User | None:
        """简单的透传，但保留了以后加逻辑的权利"""

        user = await self.uow.user_repo.get(id)
        return user

    async def get_by_email(self, email: EmailStr) -> User | None:
        """简单的透传，但保留了以后加逻辑的权利"""

        user = await self.uow.user_repo.get_by_email(email)
        return user

    async def get_by_username(self, username: str) -> User | None:
        """简单的透传，但保留了以后加逻辑的权利"""

        user = await self.uow.user_repo.get_by_username(username)
        return user

    async def user_register(self, user_in: UserCreate) -> User | None:
        """
        新增：用户注册功能
        """
        logger.debug(
            "注册请求: username=%s, email=%s",
            user_in.username,
            user_in.email,
        )

        # 1. 检查用户名是否存在
        if await self.uow.user_repo.get_by_email(email=user_in.email):
            raise ValidationError("该邮箱已被注册")
        if await self.uow.user_repo.get_by_username(username=user_in.username):
            raise ValidationError("该用户名已被注册")

        # 2. 密码加密 (这里是业务逻辑，不该放在 uow 里)

        obj_in_data = user_in.model_dump()  # Pydantic v2 用 model_dump
        obj_in_data.pop("password")  # 弹出明文密码
        obj_in_data.pop("confirm_password")  # 弹出明文密码
        obj_in_data["hashed_password"] = await get_password_hash(
            user_in.password
        )  # 添加哈希密码

        # 3. 创建用户
        try:
            user = await self.uow.user_repo.create(obj_in=obj_in_data)
        except IntegrityError as exc:
            # 并发注册时数据库唯一约束仍可能触发，这里统一转为业务错误
            raise ValidationError("用户名或邮箱已被注册") from exc

        # 4. 可能还有后续动作，比如发送欢迎邮件...
        # await email_service.send_welcome_email(users.email)

        return user

    async def user_register_with_personal_workspace(self, user_in: UserCreate) -> User | None:
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
        """
        用户更新功能
        """
        db_obj = await self.uow.user_repo.get(id=user_id)
        if not db_obj:
            raise ResourceNotFound("用户不存在")

        user = await self.uow.user_repo.update(db_obj=db_obj, obj_in=user_in)
        return user

    async def authenticate(self, user_in: UserLogin) -> User | None:
        """验证用户名和密码"""

        user = await self.uow.user_repo.get_by_username(user_in.username)
        if not user:
            return None
        if not await verify_password(user_in.password, user.hashed_password):
            return None
        return user

    async def get_multi(self, skip: int = 0, limit: int = 100) -> Sequence[User] | None:
        users = await self.uow.user_repo.get_multi(skip=skip, limit=limit)
        return users

    async def delete(self, id: int):
        # 比如删除前要做个检查？在这里加检查逻辑很方便
        # if id == 1: raise Error("不能删管理员")

        user = await self.uow.user_repo.remove(id=id)
        return user
