import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.permissions import get_permission_policy
from backend.core.exceptions import PermissionDenied
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.access import WorkspaceRole
from backend.models.orm.user import User
from backend.services.permission_types import Permission


class PermissionService:
    """配置文件驱动的工作区权限判断入口。"""

    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow
        self.policy = get_permission_policy()

    async def get_workspace_role(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkspaceRole | None:
        access_repo = getattr(self.uow, "access_repo", None)
        if access_repo is not None:
            return await access_repo.get_workspace_role(
                user_id=user_id,
                workspace_id=workspace_id,
            )
        raise RuntimeError("PermissionService requires uow.access_repo.")

    async def has_permission(
        self,
        *,
        user: User,
        workspace_id: uuid.UUID | None,
        permission: Permission,
    ) -> bool:
        if user.is_superuser and self.policy.superuser_bypass:
            return True
        if workspace_id is None:
            return self.policy.allows_missing_workspace()

        role = await self.get_workspace_role(
            user_id=user.id,
            workspace_id=workspace_id,
        )
        return self.role_has_permission(role=role, permission=permission)

    async def has_permission_for_user_id(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID | None,
        permission: Permission,
    ) -> bool:
        user_repo = getattr(self.uow, "user_repo", None)
        if user_repo is None:
            return False
        user = await user_repo.get(user_id)
        if not user:
            return False
        return await self.has_permission(
            user=user,
            workspace_id=workspace_id,
            permission=permission,
        )

    async def require_permission(
        self,
        *,
        user: User,
        workspace_id: uuid.UUID | None,
        permission: Permission,
    ) -> None:
        if await self.has_permission(
            user=user,
            workspace_id=workspace_id,
            permission=permission,
        ):
            return

        raise PermissionDenied(
            "权限不足",
            details={
                "workspace_id": str(workspace_id) if workspace_id else None,
                "permission": permission,
            },
        )

    def role_has_permission(
        self,
        *,
        role: WorkspaceRole | None,
        permission: Permission,
    ) -> bool:
        return self.policy.role_has_permission(role=role, permission=permission)

    @staticmethod
    def default_role_has_permission(
        *,
        role: WorkspaceRole | None,
        permission: Permission,
    ) -> bool:
        return get_permission_policy().role_has_permission(
            role=role,
            permission=permission,
        )

    @property
    def _session(self) -> AsyncSession:
        session = getattr(self.uow, "session", None)
        if session is None:
            raise RuntimeError(
                "PermissionService requires an active SQLAlchemy UnitOfWork session."
            )
        return session
