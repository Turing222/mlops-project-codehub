import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select

from backend.api.dependencies import (
    get_current_active_user,
    get_permission_service,
    get_uow,
)
from backend.core.exceptions import app_forbidden
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.access import AuditEvent, AuditOutcome
from backend.models.orm.user import User
from backend.models.schemas.audit_schema import (
    AuditEventListResponse,
    AuditEventResponse,
)
from backend.services.permission_service import Permission, PermissionService

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
UOW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
PermissionServiceDep = Annotated[PermissionService, Depends(get_permission_service)]
SkipParam = Annotated[int, Query(ge=0, description="跳过的记录数")]
LimitParam = Annotated[int, Query(ge=1, le=200, description="每页记录数")]


def _apply_audit_filters(
    stmt: Select,
    *,
    action: str | None,
    outcome: AuditOutcome | None,
    request_id: str | None,
    actor_user_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None,
) -> Select:
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    if request_id:
        stmt = stmt.where(AuditEvent.request_id == request_id)
    if actor_user_id:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    if workspace_id:
        stmt = stmt.where(AuditEvent.workspace_id == workspace_id)
    return stmt


async def _ensure_audit_access(
    *,
    current_user: User,
    workspace_id: uuid.UUID | None,
    permission_service: PermissionService,
) -> None:
    if current_user.is_superuser and permission_service.policy.superuser_bypass:
        return
    if workspace_id is None:
        raise app_forbidden(
            "权限不足",
            details={"scope": "global", "permission": Permission.AUDIT_READ},
        )

    await permission_service.require_permission(
        user=current_user,
        workspace_id=workspace_id,
        permission=Permission.AUDIT_READ,
    )


@router.get("/events", response_model=AuditEventListResponse)
async def list_audit_events(
    current_user: CurrentUser,
    uow: UOW,
    permission_service: PermissionServiceDep,
    skip: SkipParam = 0,
    limit: LimitParam = 20,
    action: str | None = Query(None, max_length=80),
    outcome: AuditOutcome | None = None,
    request_id: str | None = Query(None, max_length=64),
    actor_user_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> AuditEventListResponse:
    async with uow:
        await _ensure_audit_access(
            current_user=current_user,
            workspace_id=workspace_id,
            permission_service=permission_service,
        )

        count_stmt = _apply_audit_filters(
            select(func.count()).select_from(AuditEvent),
            action=action,
            outcome=outcome,
            request_id=request_id,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
        )
        total = await uow.session.scalar(count_stmt)

        stmt = _apply_audit_filters(
            select(AuditEvent),
            action=action,
            outcome=outcome,
            request_id=request_id,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
        )
        stmt = stmt.order_by(AuditEvent.created_at.desc()).offset(skip).limit(limit)
        result = await uow.session.execute(stmt)
        events = result.scalars().all()

    return AuditEventListResponse(
        items=[AuditEventResponse.model_validate(event) for event in events],
        total=total or 0,
        skip=skip,
        limit=limit,
    )
