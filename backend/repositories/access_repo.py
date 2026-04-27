import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.access import UserWorkspaceRole, Workspace, WorkspaceRole
from backend.models.orm.user import User


class AccessRepository:
    """Workspace/role access queries."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_workspace_role(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkspaceRole | None:
        stmt = select(UserWorkspaceRole.role).where(
            UserWorkspaceRole.user_id == user_id,
            UserWorkspaceRole.workspace_id == workspace_id,
        )
        result = await self.session.execute(stmt)
        role = result.scalar_one_or_none()
        return WorkspaceRole(role) if role else None

    async def get_workspace(self, workspace_id: uuid.UUID) -> Workspace | None:
        return await self.session.get(Workspace, workspace_id)

    async def get_workspace_by_slug(self, slug: str) -> Workspace | None:
        stmt = select(Workspace).where(Workspace.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_workspace(
        self,
        *,
        name: str,
        slug: str,
        owner_id: uuid.UUID | None,
    ) -> Workspace:
        workspace = Workspace(name=name, slug=slug, owner_id=owner_id)
        self.session.add(workspace)
        await self.session.flush()
        await self.session.refresh(workspace)
        return workspace

    async def update_workspace(
        self,
        *,
        workspace: Workspace,
        obj_in: dict[str, Any],
    ) -> Workspace:
        for field, value in obj_in.items():
            setattr(workspace, field, value)
        self.session.add(workspace)
        await self.session.flush()
        await self.session.refresh(workspace)
        return workspace

    async def delete_workspace(self, workspace: Workspace) -> None:
        await self.session.delete(workspace)
        await self.session.flush()

    async def add_workspace_role(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        role: WorkspaceRole,
    ) -> UserWorkspaceRole:
        user_role = UserWorkspaceRole(
            user_id=user_id,
            workspace_id=workspace_id,
            role=role,
        )
        self.session.add(user_role)
        await self.session.flush()
        await self.session.refresh(user_role)
        return user_role

    async def get_workspace_member(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> UserWorkspaceRole | None:
        stmt = select(UserWorkspaceRole).where(
            UserWorkspaceRole.user_id == user_id,
            UserWorkspaceRole.workspace_id == workspace_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_workspace_role(
        self,
        *,
        user_role: UserWorkspaceRole,
        role: WorkspaceRole,
    ) -> UserWorkspaceRole:
        user_role.role = role
        self.session.add(user_role)
        await self.session.flush()
        await self.session.refresh(user_role)
        return user_role

    async def remove_workspace_member(self, user_role: UserWorkspaceRole) -> None:
        await self.session.delete(user_role)
        await self.session.flush()

    async def count_workspace_owners(self, *, workspace_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(UserWorkspaceRole)
            .where(
                UserWorkspaceRole.workspace_id == workspace_id,
                UserWorkspaceRole.role == WorkspaceRole.OWNER,
            )
        )
        return await self.session.scalar(stmt) or 0

    async def list_workspace_members(
        self,
        *,
        workspace_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[tuple[UserWorkspaceRole, User]]:
        stmt = (
            select(UserWorkspaceRole, User)
            .join(User, User.id == UserWorkspaceRole.user_id)
            .where(UserWorkspaceRole.workspace_id == workspace_id)
            .order_by(UserWorkspaceRole.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [
            (user_role, user)
            for user_role, user in result.all()
        ]

    async def count_workspace_members(self, *, workspace_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(UserWorkspaceRole)
            .where(UserWorkspaceRole.workspace_id == workspace_id)
        )
        return await self.session.scalar(stmt) or 0

    async def list_workspaces_for_user(
        self,
        *,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[tuple[Workspace, WorkspaceRole]]:
        stmt = (
            select(Workspace, UserWorkspaceRole.role)
            .join(UserWorkspaceRole, UserWorkspaceRole.workspace_id == Workspace.id)
            .where(UserWorkspaceRole.user_id == user_id)
            .order_by(Workspace.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [
            (workspace, WorkspaceRole(role))
            for workspace, role in result.all()
        ]

    async def count_workspaces_for_user(self, *, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Workspace)
            .join(UserWorkspaceRole, UserWorkspaceRole.workspace_id == Workspace.id)
            .where(UserWorkspaceRole.user_id == user_id)
        )
        return await self.session.scalar(stmt) or 0
