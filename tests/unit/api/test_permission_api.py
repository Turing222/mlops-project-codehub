"""Permission API unit tests.

职责：验证权限元数据 endpoint 的公开响应映射；边界：直接调用 endpoint 函数，不启动 HTTP stack 或真实权限存储；副作用：无。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from backend.api.v1.endpoint import permission_api
from backend.models.enums import Permission, WorkspaceRole
from backend.services.permission_service import PermissionService


def make_user(**overrides: object) -> SimpleNamespace:
    data = {
        "id": uuid.uuid4(),
        "username": "tester",
        "email": "tester@example.com",
        "is_active": True,
        "is_superuser": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_permission_service() -> PermissionService:
    class FakeUoW:
        pass

    return PermissionService(uow=FakeUoW())


async def test_permission_policy_metadata_expands_owner_wildcard() -> None:
    permission_service = make_permission_service()
    result = await permission_api.get_permission_policy_metadata(
        _=make_user(),
        permission_service=permission_service,
    )

    assert WorkspaceRole.OWNER in result.roles
    assert Permission.WORKSPACE_READ in result.role_permissions["owner"]
    assert Permission.ROLE_MANAGE in result.role_permissions["owner"]
    assert Permission.ROLE_MANAGE not in result.role_permissions["member"]
    assert {item.value for item in result.permissions} == set(Permission)
