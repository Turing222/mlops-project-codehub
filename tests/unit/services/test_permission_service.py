import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.config.loader import ConfigurationError
from backend.config.permissions import load_permission_policy
from backend.core.exceptions import AppException
from backend.models.orm.access import WorkspaceRole
from backend.models.orm.user import User
from backend.services.permission_service import Permission, PermissionService


def make_user(*, is_superuser: bool = False) -> User:
    return User(
        id=uuid.uuid4(),
        username="user",
        email="user@example.com",
        hashed_password="hashed",
        is_active=True,
        is_superuser=is_superuser,
    )


def make_service_with_role(role: WorkspaceRole | None) -> PermissionService:
    access_repo = SimpleNamespace(get_workspace_role=AsyncMock(return_value=role))
    user = make_user()
    user_repo = SimpleNamespace(get=AsyncMock(return_value=user))
    return PermissionService(
        uow=SimpleNamespace(access_repo=access_repo, user_repo=user_repo)
    )


@pytest.mark.asyncio
async def test_superuser_has_permission_without_role_lookup():
    service = make_service_with_role(None)
    user = make_user(is_superuser=True)

    allowed = await service.has_permission(
        user=user,
        workspace_id=None,
        permission=Permission.WORKSPACE_MANAGE,
    )

    assert allowed is True
    service.uow.access_repo.get_workspace_role.assert_not_called()


@pytest.mark.asyncio
async def test_member_role_allows_file_write_but_not_role_manage():
    service = make_service_with_role(WorkspaceRole.MEMBER)
    user = make_user()
    workspace_id = uuid.uuid4()

    assert (
        await service.has_permission(
            user=user,
            workspace_id=workspace_id,
            permission=Permission.FILE_WRITE,
        )
        is True
    )
    assert (
        await service.has_permission(
            user=user,
            workspace_id=workspace_id,
            permission=Permission.ROLE_MANAGE,
        )
        is False
    )


@pytest.mark.asyncio
async def test_require_permission_raises_permission_denied():
    service = make_service_with_role(WorkspaceRole.VIEWER)

    with pytest.raises(AppException) as exc_info:
        await service.require_permission(
            user=make_user(),
            workspace_id=uuid.uuid4(),
            permission=Permission.FILE_DELETE,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_has_permission_for_user_id_loads_user_and_role():
    service = make_service_with_role(WorkspaceRole.VIEWER)

    allowed = await service.has_permission_for_user_id(
        user_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        permission=Permission.CHAT_READ,
    )

    assert allowed is True
    service.uow.user_repo.get.assert_awaited_once()


def test_configured_owner_wildcard_allows_every_permission():
    policy = load_permission_policy()

    for permission in Permission:
        assert policy.role_has_permission(
            role=WorkspaceRole.OWNER,
            permission=permission,
        )


def test_invalid_permission_config_rejects_unknown_permission(tmp_path: Path):
    config_dir = tmp_path / "configs"
    access_dir = config_dir / "access"
    access_dir.mkdir(parents=True)
    (access_dir / "permissions.yaml").write_text(
        """
version: 1
permissions:
  workspace:read: {}
  workspace:manage: {}
  role:manage: {}
  file:read: {}
  file:write: {}
  file:delete: {}
  chat:read: {}
  chat:write: {}
  audit:read: {}
roles:
  owner:
    permissions: ["*"]
  admin:
    permissions: ["workspace:read", "unknown:permission"]
  member:
    permissions: ["workspace:read"]
  viewer:
    permissions: ["workspace:read"]
defaults:
  superuser_bypass: true
  missing_workspace: deny
  missing_role: deny
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        load_permission_policy(config_dir=config_dir)
