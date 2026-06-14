"""User service.

职责：封装用户注册、认证、更新、删除和个人工作区创建。
边界：本模块不签发 token、不处理 HTTP 响应；认证接口只返回匹配的用户对象。
风险：注册前检查不能替代数据库唯一约束，并发冲突仍需捕获 IntegrityError。
"""

import logging
import secrets
import string
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import (
    app_bad_request,
    app_not_found,
    app_validation_error,
)
from backend.core.security import get_password_hash, verify_password
from backend.models.enums import WorkspaceRole
from backend.models.orm.user import User
from backend.models.schemas.user_schema import (
    UserCreate,
    UserLogin,
    UserUpdate,
)
from backend.repositories.user_repo import UserCreateData
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

        if user_in.email and await self.uow.user_repo.get_by_email(email=user_in.email):
            raise app_validation_error(
                "该邮箱已被注册", code="EMAIL_ALREADY_REGISTERED"
            )
        if await self.uow.user_repo.get_by_username(username=user_in.username):
            raise app_validation_error(
                "该用户名已被注册",
                code="USERNAME_ALREADY_REGISTERED",
            )

        hashed_pw = (
            await get_password_hash(user_in.password) if user_in.password else None
        )
        obj_in_data = UserCreateData(
            username=user_in.username,
            email=str(user_in.email) if user_in.email else None,
            hashed_password=hashed_pw,
            max_tokens=user_in.max_tokens,
            phone=user_in.phone,
        )

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

        if user_in.username is not None and user_in.username != db_obj.username:
            existing_user = await self.uow.user_repo.get_by_username(user_in.username)
            if existing_user and existing_user.id != user_id:
                raise app_validation_error(
                    "该用户名已被注册",
                    code="USERNAME_ALREADY_REGISTERED",
                )

        if user_in.email is not None and user_in.email != db_obj.email:
            existing_user = await self.uow.user_repo.get_by_email(str(user_in.email))
            if existing_user and existing_user.id != user_id:
                raise app_validation_error(
                    "该邮箱已被注册",
                    code="EMAIL_ALREADY_REGISTERED",
                )

        if user_in.phone is not None and user_in.phone != db_obj.phone:
            existing_user = await self.uow.user_repo.get_by_phone(user_in.phone)
            if existing_user and existing_user.id != user_id:
                raise app_validation_error(
                    "该手机号已被注册",
                    code="PHONE_ALREADY_REGISTERED",
                )

        try:
            user = await self.uow.user_repo.update(db_obj=db_obj, obj_in=user_in)
        except IntegrityError as exc:
            raise app_validation_error(
                "用户名、邮箱或手机号已被注册",
                code="USER_ALREADY_REGISTERED",
            ) from exc
        return user

    async def authenticate(self, user_in: UserLogin) -> User | None:
        """验证用户名和密码，失败时返回 None。"""

        user = await self.uow.user_repo.get_by_username(user_in.username)
        if not user or not user.hashed_password:
            return None
        if not await verify_password(user_in.password, user.hashed_password):
            return None
        return user

    async def get_multi(self, skip: int = 0, limit: int = 100) -> Sequence[User]:
        users = await self.uow.user_repo.get_multi(skip=skip, limit=limit)
        return users

    async def delete(self, id: int) -> User | None:
        user = await self.uow.user_repo.remove(id=id)
        return user

    # ── 手机号 / Google OAuth 自动注册 ──────────────────────────

    async def _generate_unique_username(self) -> str:
        """生成不与现有用户冲突的 user_ 前缀用户名。"""
        for _ in range(10):
            suffix = "".join(
                secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8)
            )
            username = f"user_{suffix}"
            if not await self.uow.user_repo.get_by_username(username):
                return username
        msg = "无法生成唯一用户名"
        raise RuntimeError(msg)

    async def find_or_create_by_phone(
        self, phone: str, *, allow_new_registration: bool = True
    ) -> User:
        """按手机号查找用户，不存在则自动注册。

        Args:
            allow_new_registration: 当 False 且用户不存在时，抛出 REGISTRATION_CLOSED 异常
                而非自动创建。用于封闭内测阶段的新用户注册门控。
        """
        user = await self.uow.user_repo.get_by_phone(phone)
        if user:
            return user

        if not allow_new_registration:
            raise app_bad_request(
                "当前处于封闭内测阶段，暂不开放公开注册",
                code="REGISTRATION_CLOSED",
            )

        username = await self._generate_unique_username()
        obj_in_data = UserCreateData(
            username=username,
            email=None,
            hashed_password=None,
            max_tokens=100000,
            phone=phone,
            auth_provider="phone",
        )
        try:
            async with self.uow.savepoint():
                user = await self.uow.user_repo.create(obj_in=obj_in_data)
                await self._create_personal_workspace_for_user(user)
        except IntegrityError:
            user = await self.uow.user_repo.get_by_phone(phone)
            if user is None:
                raise
        return user

    async def find_or_create_by_google(
        self,
        google_sub: str,
        email: str | None,
        name: str | None,
        *,
        allow_new_registration: bool = True,
    ) -> User:
        """按 Google sub 查找用户，不存在则自动注册或关联已有邮箱账号。

        Args:
            allow_new_registration: 当 False 且无现有用户时，抛出 REGISTRATION_CLOSED 异常
                而非自动创建。用于封闭内测阶段的新用户注册门控。
        """
        # 1. 按 google_sub 查找
        user = await self.uow.user_repo.get_by_google_sub(google_sub)
        if user:
            return user

        # 2. 按 email 查找并关联（如果 email 已注册）
        if email:
            user = await self.uow.user_repo.get_by_email(email)
            if user:
                await self.link_google_account(user.id, google_sub)
                return user

        # 3. 注册门控
        if not allow_new_registration:
            raise app_bad_request(
                "当前处于封闭内测阶段，暂不开放公开注册",
                code="REGISTRATION_CLOSED",
            )

        # 4. 自动创建新用户
        username = await self._generate_unique_username()
        obj_in_data = UserCreateData(
            username=username,
            email=email,
            hashed_password=None,
            max_tokens=100000,
            auth_provider="google",
            google_sub=google_sub,
        )
        try:
            async with self.uow.savepoint():
                user = await self.uow.user_repo.create(obj_in=obj_in_data)
                await self._create_personal_workspace_for_user(user)
        except IntegrityError:
            user = await self.uow.user_repo.get_by_google_sub(google_sub)
            if user is None and email:
                user = await self.uow.user_repo.get_by_email(email)
                if user is not None:
                    user = await self.link_google_account(user.id, google_sub)
            if user is None:
                raise
        return user

    async def link_google_account(self, user_id: uuid.UUID, google_sub: str) -> User:
        """将 Google 账号关联到已有用户。"""
        user = await self.uow.user_repo.get(id=user_id)
        if not user:
            raise app_not_found("用户不存在", code="USER_NOT_FOUND")

        auth_provider = user.auth_provider or "google"
        await self.uow.user_repo.update(
            db_obj=user,
            obj_in={"google_sub": google_sub, "auth_provider": auth_provider},
        )
        return user
