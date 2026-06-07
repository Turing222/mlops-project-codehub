from fastapi import Depends, Request

from backend.api.deps.uow import get_uow
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.client_ip import ClientIPResolver
from backend.services.audit_service import AuditRequestContext, AuditService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork

_client_ip_resolver = ClientIPResolver(settings.RATE_LIMIT_TRUSTED_PROXY_CIDRS)


def get_audit_service(
    request: Request,
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> AuditService:
    peer_ip = request.client.host if request.client else None
    client_ip = _client_ip_resolver.resolve(
        peer_ip,
        request.headers.get("x-real-ip"),
    )
    return AuditService(
        uow=uow,
        independent_uow_factory=lambda: SQLAlchemyUnitOfWork(
            request.app.state.session_factory
        ),
        request_context=AuditRequestContext(
            ip=client_ip,
            user_agent=request.headers.get("user-agent"),
            request_id=getattr(request.state, "request_id", None),
        ),
    )
