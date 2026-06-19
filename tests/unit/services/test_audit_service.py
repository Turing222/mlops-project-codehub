"""Audit service unit tests.

职责：验证 AuditService 的事件记录、capture 上下文管理器和 FastAPI Depends 降级行为；边界：使用 FakeSession，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.core.exceptions import AppException, app_forbidden
from backend.models.orm.access import AuditOutcome
from backend.services.audit_service import (
    AuditAction,
    AuditRequestContext,
    AuditService,
    capture_audit,
    record_audit,
)


class FakeUow:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.committed = False
        self.audit_repo = self

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None:
            self.committed = True
        return False

    async def add(self, event: object) -> None:
        self.events.append(event)

    async def commit(self) -> None:
        self.committed = True


class FakeUowFactory:
    def __init__(self) -> None:
        self.uow = FakeUow()

    def __call__(self) -> FakeUow:
        return self.uow


def make_audit_service() -> tuple[AuditService, FakeUowFactory]:
    uow_factory = FakeUowFactory()
    service = AuditService(
        uow=SimpleNamespace(),
        independent_uow_factory=uow_factory,
        request_context=AuditRequestContext(
            ip="127.0.0.1",
            user_agent="pytest",
            request_id="req-1",
        ),
    )
    return service, uow_factory


async def test_capture_records_success_event_on_allowed() -> None:
    service, uow_factory = make_audit_service()
    resource_id = uuid.uuid4()

    async with service.capture(
        action=AuditAction.USER_CREATE,
        actor_user_id=uuid.uuid4(),
        resource_type="user",
    ) as audit:
        audit.set_resource(resource_id=resource_id)
        audit.add_metadata(username="alice")

    event = uow_factory.uow.events[0]
    assert event.action == AuditAction.USER_CREATE
    assert event.outcome == AuditOutcome.SUCCESS
    assert event.resource_id == resource_id
    assert event.event_metadata["username"] == "alice"
    assert event.ip == "127.0.0.1"
    assert uow_factory.uow.committed is True


async def test_capture_records_denied_event_and_reraises_original() -> None:
    service, uow_factory = make_audit_service()

    with pytest.raises(AppException):
        async with service.capture(action=AuditAction.PERMISSION_DENIED):
            raise app_forbidden("nope")

    event = uow_factory.uow.events[0]
    assert event.outcome == AuditOutcome.DENIED
    assert event.event_metadata["error_type"] == "AppException"


async def test_capture_noops_for_fastapi_depends_default() -> None:
    async with capture_audit(object(), action=AuditAction.USER_UPDATE) as audit:
        audit.add_metadata(updated=True)


async def test_record_audit_noops_when_audit_service_is_none() -> None:
    await record_audit(object(), action=AuditAction.USER_UPDATE)
