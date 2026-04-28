import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from backend.core.exceptions import PermissionDenied, ValidationError
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.access import WorkspaceRole
from backend.models.schemas.workspace_schema import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberUpdate,
    WorkspaceUpdate,
)
from backend.services.workspace_service import WorkspaceService


def make_user(**overrides):
    data = {
        "id": uuid.uuid4(),
        "username": "alice",
        "email": "alice@example.com",
        "is_active": True,
        "is_superuser": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_workspace(**overrides):
    now = datetime.now(UTC)
    data = {
        "id": uuid.uuid4(),
        "name": "Team",
        "slug": "team",
        "owner_id": uuid.uuid4(),
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_user_role(**overrides):
    now = datetime.now(UTC)
    data = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "role": WorkspaceRole.MEMBER,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_service(*, role: WorkspaceRole | None = WorkspaceRole.OWNER):
    workspace = make_workspace()
    member_user = make_user(username="bob", email="bob@example.com")
    member_role = make_user_role(
        user_id=member_user.id,
        workspace_id=workspace.id,
        role=WorkspaceRole.MEMBER,
    )
    access_repo = SimpleNamespace(
        get_workspace=AsyncMock(return_value=workspace),
        get_workspace_by_slug=AsyncMock(return_value=None),
        create_workspace=AsyncMock(return_value=workspace),
        add_workspace_role=AsyncMock(),
        update_workspace=AsyncMock(return_value=workspace),
        delete_workspace=AsyncMock(),
        soft_delete_workspace=AsyncMock(),  # R7: 软删除接口
        list_workspaces_for_user=AsyncMock(return_value=[(workspace, role)] if role else []),
        count_workspaces_for_user=AsyncMock(return_value=1 if role else 0),
        get_workspace_role=AsyncMock(return_value=role),
        get_workspace_member=AsyncMock(return_value=member_role),
        update_workspace_role=AsyncMock(return_value=member_role),
        remove_workspace_member=AsyncMock(),
        count_workspace_owners=AsyncMock(return_value=2),
        list_workspace_members=AsyncMock(return_value=[(member_role, member_user)]),
        count_workspace_members=AsyncMock(return_value=1),
    )
    user_repo = SimpleNamespace(get=AsyncMock(return_value=member_user))
    uow = cast(
        AbstractUnitOfWork,
        SimpleNamespace(access_repo=access_repo, user_repo=user_repo),
    )
    service = WorkspaceService(uow=uow)
    return service, access_repo, workspace, member_user, member_role


def test_workspace_create_normalizes_slug():
    workspace_in = WorkspaceCreate(name="Alice Team", slug="Alice-Team")

    assert workspace_in.slug == "alice-team"


@pytest.mark.asyncio
async def test_create_workspace_assigns_current_user_as_owner():
    service, access_repo, workspace, _, _ = make_service()
    user = make_user()

    result, role = await service.create_workspace(
        current_user=user,
        workspace_in=WorkspaceCreate(name="Alice Team", slug="alice-team"),
    )

    assert result is workspace
    assert role == WorkspaceRole.OWNER
    access_repo.create_workspace.assert_awaited_once_with(
        name="Alice Team",
        slug="alice-team",
        owner_id=user.id,
    )
    access_repo.add_workspace_role.assert_awaited_once_with(
        user_id=user.id,
        workspace_id=workspace.id,
        role=WorkspaceRole.OWNER,
    )


@pytest.mark.asyncio
async def test_create_workspace_rejects_duplicate_slug():
    existing = make_workspace(slug="taken")
    service, access_repo, _, _, _ = make_service()
    access_repo.get_workspace_by_slug.return_value = existing

    with pytest.raises(ValidationError):
        await service.create_workspace(
            current_user=make_user(),
            workspace_in=WorkspaceCreate(name="Taken", slug="taken"),
        )

    access_repo.create_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_workspace_requires_manage_permission():
    service, access_repo, workspace, _, _ = make_service(role=WorkspaceRole.MEMBER)

    with pytest.raises(PermissionDenied):
        await service.update_workspace(
            current_user=make_user(),
            workspace_id=workspace.id,
            workspace_in=WorkspaceUpdate(name="New Name"),
        )

    access_repo.update_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_workspace_requires_owner_role():
    service, access_repo, workspace, _, _ = make_service(role=WorkspaceRole.ADMIN)

    with pytest.raises(PermissionDenied):
        await service.delete_workspace(
            current_user=make_user(),
            workspace_id=workspace.id,
        )

    access_repo.delete_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_superuser_can_delete_workspace_without_owner_role():
    service, access_repo, workspace, _, _ = make_service(role=None)

    await service.delete_workspace(
        current_user=make_user(is_superuser=True),
        workspace_id=workspace.id,
    )

    access_repo.soft_delete_workspace.assert_awaited_once_with(workspace)


def test_workspace_member_create_defaults_to_member_role():
    member_in = WorkspaceMemberCreate(user_id=uuid.uuid4())

    assert member_in.role == WorkspaceRole.MEMBER


@pytest.mark.asyncio
async def test_add_workspace_member_uses_default_member_role():
    service, access_repo, workspace, member_user, _ = make_service(role=WorkspaceRole.ADMIN)
    access_repo.get_workspace_member.return_value = None

    result, user = await service.add_workspace_member(
        current_user=make_user(),
        workspace_id=workspace.id,
        member_in=WorkspaceMemberCreate(user_id=member_user.id),
    )

    assert user is member_user
    assert result is access_repo.add_workspace_role.return_value
    access_repo.add_workspace_role.assert_awaited_once_with(
        user_id=member_user.id,
        workspace_id=workspace.id,
        role=WorkspaceRole.MEMBER,
    )


@pytest.mark.asyncio
async def test_admin_cannot_appoint_owner():
    service, access_repo, workspace, member_user, _ = make_service(role=WorkspaceRole.ADMIN)
    access_repo.get_workspace_member.return_value = None

    with pytest.raises(PermissionDenied):
        await service.add_workspace_member(
            current_user=make_user(),
            workspace_id=workspace.id,
            member_in=WorkspaceMemberCreate(
                user_id=member_user.id,
                role=WorkspaceRole.OWNER,
            ),
        )

    access_repo.add_workspace_role.assert_not_awaited()


@pytest.mark.asyncio
async def test_cannot_downgrade_last_owner():
    service, access_repo, workspace, member_user, member_role = make_service(
        role=WorkspaceRole.OWNER,
    )
    member_role.role = WorkspaceRole.OWNER
    access_repo.count_workspace_owners.return_value = 1

    with pytest.raises(ValidationError):
        await service.update_workspace_member(
            current_user=make_user(),
            workspace_id=workspace.id,
            user_id=member_user.id,
            member_in=WorkspaceMemberUpdate(role=WorkspaceRole.ADMIN),
        )

    access_repo.update_workspace_role.assert_not_awaited()


@pytest.mark.asyncio
async def test_cannot_remove_last_owner():
    service, access_repo, workspace, member_user, member_role = make_service(
        role=WorkspaceRole.OWNER,
    )
    member_role.role = WorkspaceRole.OWNER
    access_repo.count_workspace_owners.return_value = 1

    with pytest.raises(ValidationError):
        await service.remove_workspace_member(
            current_user=make_user(),
            workspace_id=workspace.id,
            user_id=member_user.id,
        )

    access_repo.remove_workspace_member.assert_not_awaited()
