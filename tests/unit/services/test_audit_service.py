import uuid
from types import SimpleNamespace

import pytest

from backend.core.exceptions import PermissionDenied
from backend.models.orm.access import AuditOutcome
from backend.services.audit_service import (
    AuditAction,
    AuditRequestContext,
    AuditService,
    capture_audit,
    record_audit,
)


class FakeSession:
    def __init__(self):
        self.events = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def add(self, event):
        self.events.append(event)

    async def commit(self):
        self.committed = True


class FakeSessionFactory:
    def __init__(self):
        self.session = FakeSession()

    def __call__(self):
        return self.session


def make_audit_service() -> tuple[AuditService, FakeSessionFactory]:
    session_factory = FakeSessionFactory()
    service = AuditService(
        uow=SimpleNamespace(),
        session_factory=session_factory,
        request_context=AuditRequestContext(
            ip="127.0.0.1",
            user_agent="pytest",
            request_id="req-1",
        ),
    )
    return service, session_factory


@pytest.mark.asyncio
async def test_capture_records_success_event():
    service, session_factory = make_audit_service()
    resource_id = uuid.uuid4()

    async with service.capture(
        action=AuditAction.USER_CREATE,
        actor_user_id=uuid.uuid4(),
        resource_type="user",
    ) as audit:
        audit.set_resource(resource_id=resource_id)
        audit.add_metadata(username="alice")

    event = session_factory.session.events[0]
    assert event.action == AuditAction.USER_CREATE
    assert event.outcome == AuditOutcome.SUCCESS
    assert event.resource_id == resource_id
    assert event.event_metadata["username"] == "alice"
    assert event.ip == "127.0.0.1"
    assert session_factory.session.committed is True


@pytest.mark.asyncio
async def test_capture_records_denied_event_and_reraises():
    service, session_factory = make_audit_service()

    with pytest.raises(PermissionDenied):
        async with service.capture(action=AuditAction.PERMISSION_DENIED):
            raise PermissionDenied("nope")

    event = session_factory.session.events[0]
    assert event.outcome == AuditOutcome.DENIED
    assert event.event_metadata["error_type"] == "PermissionDenied"


@pytest.mark.asyncio
async def test_capture_audit_noops_for_fastapi_depends_default():
    async with capture_audit(object(), action=AuditAction.USER_UPDATE) as audit:
        audit.add_metadata(updated=True)


@pytest.mark.asyncio
async def test_record_audit_noops_for_non_audit_service():
    await record_audit(object(), action=AuditAction.USER_UPDATE)
