import uuid
from types import SimpleNamespace

import pytest

from backend.api.v1.endpoint import permission_api
from backend.models.orm.access import WorkspaceRole
from backend.services.permission_service import Permission


def make_user(**overrides):
    data = {
        "id": uuid.uuid4(),
        "username": "tester",
        "email": "tester@example.com",
        "is_active": True,
        "is_superuser": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_permission_policy_metadata_expands_owner_wildcard():
    result = await permission_api.get_permission_policy_metadata(make_user())

    assert WorkspaceRole.OWNER in result.roles
    assert Permission.WORKSPACE_READ in result.role_permissions["owner"]
    assert Permission.ROLE_MANAGE in result.role_permissions["owner"]
    assert Permission.ROLE_MANAGE not in result.role_permissions["member"]
    assert {item.value for item in result.permissions} == set(Permission)
