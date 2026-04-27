import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError

from backend.core.exceptions import PermissionDenied, ResourceNotFound, ValidationError
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.access import UserWorkspaceRole, Workspace, WorkspaceRole
from backend.models.orm.user import User
from backend.models.schemas.workspace_schema import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberUpdate,
    WorkspaceUpdate,
)
from backend.services.base import BaseService
from backend.services.permission_service import Permission, PermissionService


class WorkspaceService(BaseService[AbstractUnitOfWork]):
    def __init__(self, uow: AbstractUnitOfWork):
        super().__init__(uow)
        self.permission_service = PermissionService(uow)

    async def create_workspace(
        self,
        *,
        current_user: User,
        workspace_in: WorkspaceCreate,
    ) -> tuple[Workspace, WorkspaceRole]:
        await self._ensure_slug_available(workspace_in.slug)
        try:
            workspace = await self.uow.access_repo.create_workspace(
                name=workspace_in.name,
                slug=workspace_in.slug,
                owner_id=current_user.id,
            )
            await self.uow.access_repo.add_workspace_role(
                user_id=current_user.id,
                workspace_id=workspace.id,
                role=WorkspaceRole.OWNER,
            )
        except IntegrityError as exc:
            raise ValidationError("工作区 slug 已存在") from exc
        return workspace, WorkspaceRole.OWNER

    async def list_user_workspaces(
        self,
        *,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[tuple[Workspace, WorkspaceRole]], int]:
        items = await self.uow.access_repo.list_workspaces_for_user(
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )
        total = await self.uow.access_repo.count_workspaces_for_user(
            user_id=current_user.id,
        )
        return items, total

    async def get_workspace(
        self,
        *,
        current_user: User,
        workspace_id: uuid.UUID,
    ) -> tuple[Workspace, WorkspaceRole | None]:
        workspace = await self._get_workspace_or_404(workspace_id)
        role = await self.permission_service.get_workspace_role(
            user_id=current_user.id,
            workspace_id=workspace_id,
        )
        await self.permission_service.require_permission(
            user=current_user,
            workspace_id=workspace_id,
            permission=Permission.WORKSPACE_READ,
        )
        return workspace, role

    async def update_workspace(
        self,
        *,
        current_user: User,
        workspace_id: uuid.UUID,
        workspace_in: WorkspaceUpdate,
    ) -> tuple[Workspace, WorkspaceRole | None]:
        workspace = await self._get_workspace_or_404(workspace_id)
        role = await self.permission_service.get_workspace_role(
            user_id=current_user.id,
            workspace_id=workspace_id,
        )
        await self.permission_service.require_permission(
            user=current_user,
            workspace_id=workspace_id,
            permission=Permission.WORKSPACE_MANAGE,
        )

        update_data = workspace_in.model_dump(exclude_unset=True)
        slug = update_data.get("slug")
        if slug and slug != workspace.slug:
            await self._ensure_slug_available(slug, exclude_workspace_id=workspace_id)

        try:
            workspace = await self.uow.access_repo.update_workspace(
                workspace=workspace,
                obj_in=update_data,
            )
        except IntegrityError as exc:
            raise ValidationError("工作区 slug 已存在") from exc
        return workspace, role

    async def delete_workspace(
        self,
        *,
        current_user: User,
        workspace_id: uuid.UUID,
    ) -> None:
        workspace = await self._get_workspace_or_404(workspace_id)
        if current_user.is_superuser and self.permission_service.policy.superuser_bypass:
            await self.uow.access_repo.delete_workspace(workspace)
            return

        role = await self.permission_service.get_workspace_role(
            user_id=current_user.id,
            workspace_id=workspace_id,
        )
        if role != WorkspaceRole.OWNER:
            raise PermissionDenied(
                "只有工作区 owner 可以删除工作区",
                details={"workspace_id": str(workspace_id)},
            )
        await self.uow.access_repo.delete_workspace(workspace)

    async def list_workspace_members(
        self,
        *,
        current_user: User,
        workspace_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[tuple[UserWorkspaceRole, User]], int]:
        await self._get_workspace_or_404(workspace_id)
        await self.permission_service.require_permission(
            user=current_user,
            workspace_id=workspace_id,
            permission=Permission.WORKSPACE_READ,
        )
        items = await self.uow.access_repo.list_workspace_members(
            workspace_id=workspace_id,
            skip=skip,
            limit=limit,
        )
        total = await self.uow.access_repo.count_workspace_members(
            workspace_id=workspace_id,
        )
        return items, total

    async def add_workspace_member(
        self,
        *,
        current_user: User,
        workspace_id: uuid.UUID,
        member_in: WorkspaceMemberCreate,
    ) -> tuple[UserWorkspaceRole, User]:
        await self._get_workspace_or_404(workspace_id)
        await self._require_role_manage(
            current_user=current_user,
            workspace_id=workspace_id,
        )
        await self._ensure_owner_change_allowed(
            current_user=current_user,
            workspace_id=workspace_id,
            target_role=member_in.role,
        )

        user = await self.uow.user_repo.get(member_in.user_id)
        if not user:
            raise ResourceNotFound("用户不存在")

        existing = await self.uow.access_repo.get_workspace_member(
            user_id=member_in.user_id,
            workspace_id=workspace_id,
        )
        if existing:
            raise ValidationError("用户已经是该工作区成员")

        user_role = await self.uow.access_repo.add_workspace_role(
            user_id=member_in.user_id,
            workspace_id=workspace_id,
            role=member_in.role,
        )
        return user_role, user

    async def update_workspace_member(
        self,
        *,
        current_user: User,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        member_in: WorkspaceMemberUpdate,
    ) -> tuple[UserWorkspaceRole, User]:
        await self._get_workspace_or_404(workspace_id)
        await self._require_role_manage(
            current_user=current_user,
            workspace_id=workspace_id,
        )
        user_role = await self._get_member_or_404(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        current_role = WorkspaceRole(user_role.role)
        new_role = member_in.role

        await self._ensure_owner_change_allowed(
            current_user=current_user,
            workspace_id=workspace_id,
            target_role=new_role,
            existing_role=current_role,
        )
        await self._ensure_not_removing_last_owner(
            workspace_id=workspace_id,
            current_role=current_role,
            next_role=new_role,
        )

        user = await self.uow.user_repo.get(user_id)
        if not user:
            raise ResourceNotFound("用户不存在")

        user_role = await self.uow.access_repo.update_workspace_role(
            user_role=user_role,
            role=new_role,
        )
        return user_role, user

    async def remove_workspace_member(
        self,
        *,
        current_user: User,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        await self._get_workspace_or_404(workspace_id)
        await self._require_role_manage(
            current_user=current_user,
            workspace_id=workspace_id,
        )
        user_role = await self._get_member_or_404(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        current_role = WorkspaceRole(user_role.role)

        await self._ensure_owner_change_allowed(
            current_user=current_user,
            workspace_id=workspace_id,
            existing_role=current_role,
        )
        await self._ensure_not_removing_last_owner(
            workspace_id=workspace_id,
            current_role=current_role,
            next_role=None,
        )
        await self.uow.access_repo.remove_workspace_member(user_role)

    async def _get_workspace_or_404(self, workspace_id: uuid.UUID) -> Workspace:
        workspace = await self.uow.access_repo.get_workspace(workspace_id)
        if not workspace:
            raise ResourceNotFound("工作区不存在")
        return workspace

    async def _ensure_slug_available(
        self,
        slug: str,
        *,
        exclude_workspace_id: uuid.UUID | None = None,
    ) -> None:
        existing = await self.uow.access_repo.get_workspace_by_slug(slug)
        if existing and existing.id != exclude_workspace_id:
            raise ValidationError("工作区 slug 已存在")

    async def _require_role_manage(
        self,
        *,
        current_user: User,
        workspace_id: uuid.UUID,
    ) -> None:
        await self.permission_service.require_permission(
            user=current_user,
            workspace_id=workspace_id,
            permission=Permission.ROLE_MANAGE,
        )

    async def _get_member_or_404(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> UserWorkspaceRole:
        user_role = await self.uow.access_repo.get_workspace_member(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        if not user_role:
            raise ResourceNotFound("工作区成员不存在")
        return user_role

    async def _ensure_owner_change_allowed(
        self,
        *,
        current_user: User,
        workspace_id: uuid.UUID,
        target_role: WorkspaceRole | None = None,
        existing_role: WorkspaceRole | None = None,
    ) -> None:
        if current_user.is_superuser and self.permission_service.policy.superuser_bypass:
            return
        if target_role != WorkspaceRole.OWNER and existing_role != WorkspaceRole.OWNER:
            return

        actor_role = await self.permission_service.get_workspace_role(
            user_id=current_user.id,
            workspace_id=workspace_id,
        )
        if actor_role == WorkspaceRole.OWNER:
            return

        raise PermissionDenied(
            "只有工作区 owner 可以管理 owner 角色",
            details={"workspace_id": str(workspace_id)},
        )

    async def _ensure_not_removing_last_owner(
        self,
        *,
        workspace_id: uuid.UUID,
        current_role: WorkspaceRole,
        next_role: WorkspaceRole | None,
    ) -> None:
        if current_role != WorkspaceRole.OWNER or next_role == WorkspaceRole.OWNER:
            return

        owner_count = await self.uow.access_repo.count_workspace_owners(
            workspace_id=workspace_id,
        )
        if owner_count <= 1:
            raise ValidationError("不能降级或移除最后一个 owner")
