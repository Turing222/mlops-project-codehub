from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.v1.endpoint import audit_api
from backend.core.exceptions import PermissionDenied
from backend.services.permission_service import Permission


class DummyUoW:
    def __init__(self):
        self.session = SimpleNamespace(
            scalar=AsyncMock(return_value=0),
            execute=AsyncMock(return_value=DummyResult()),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyResult:
    def scalars(self):
        return self

    def all(self):
        return []


def make_user(**overrides):
    now = datetime.now(UTC)
    data = {
        "id": uuid.uuid4(),
        "username": "tester",
        "email": "tester@example.com",
        "is_active": True,
        "is_superuser": False,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_permission_service():
    return SimpleNamespace(
        policy=SimpleNamespace(superuser_bypass=True),
        require_permission=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_workspace_audit_events_require_audit_read_permission():
    workspace_id = uuid.uuid4()
    current_user = make_user()
    permission_service = make_permission_service()

    result = await audit_api.list_audit_events(
        current_user=current_user,
        uow=DummyUoW(),
        permission_service=permission_service,
        workspace_id=workspace_id,
        action=None,
        request_id=None,
    )

    assert result.total == 0
    permission_service.require_permission.assert_awaited_once_with(
        user=current_user,
        workspace_id=workspace_id,
        permission=Permission.AUDIT_READ,
    )


@pytest.mark.asyncio
async def test_non_superuser_cannot_read_global_audit_events():
    permission_service = make_permission_service()

    with pytest.raises(PermissionDenied) as exc_info:
        await audit_api.list_audit_events(
            current_user=make_user(),
            uow=DummyUoW(),
            permission_service=permission_service,
            workspace_id=None,
            action=None,
            request_id=None,
        )

    assert exc_info.value.status_code == 403
    permission_service.require_permission.assert_not_awaited()


@pytest.mark.asyncio
async def test_superuser_can_read_global_audit_events_without_role_check():
    permission_service = make_permission_service()

    result = await audit_api.list_audit_events(
        current_user=make_user(is_superuser=True),
        uow=DummyUoW(),
        permission_service=permission_service,
        workspace_id=None,
        action=None,
        request_id=None,
    )

    assert result.total == 0
    permission_service.require_permission.assert_not_awaited()
