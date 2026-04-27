from fastapi import Depends, Request

from backend.api.deps.uow import get_uow
from backend.domain.interfaces import AbstractUnitOfWork
from backend.services.audit_service import AuditRequestContext, AuditService


def get_audit_service(
    request: Request,
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> AuditService:
    client_ip = request.client.host if request.client else None
    return AuditService(
        uow=uow,
        session_factory=request.app.state.session_factory,
        request_context=AuditRequestContext(
            ip=client_ip,
            user_agent=request.headers.get("user-agent"),
            request_id=getattr(request.state, "request_id", None),
        ),
    )
