"""Audit service.

职责：记录认证、权限、用户、工作区、文件和聊天等业务审计事件。
边界：本模块不参与业务授权决策，只在调用方指定时写入审计表。
失败处理：独立审计写入失败只记录日志，不阻断主业务流程。
"""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.exceptions import AppException
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.access import AuditEvent, AuditOutcome

logger = logging.getLogger(__name__)


class AuditAction(StrEnum):
    """审计事件动作枚举。"""

    AUTH_LOGIN_SUCCESS = "auth.login_success"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    PERMISSION_DENIED = "permission.denied"
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_IMPORT_CSV = "user.import_csv"
    WORKSPACE_CREATE = "workspace.create"
    WORKSPACE_UPDATE = "workspace.update"
    WORKSPACE_DELETE = "workspace.delete"
    WORKSPACE_MEMBER_ADD = "workspace.member_add"
    WORKSPACE_MEMBER_UPDATE = "workspace.member_update"
    WORKSPACE_MEMBER_REMOVE = "workspace.member_remove"
    FILE_UPLOAD_SUBMIT = "file.upload_submit"
    CHAT_QUERY_SENT = "chat.query_sent"
    CHAT_QUERY_STREAM = "chat.query_stream"


@dataclass(slots=True)
class AuditRequestContext:
    """来自 HTTP 请求的审计上下文。"""

    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


@dataclass(slots=True)
class AuditCapture:
    """上下文管理器内可补充的审计资源信息。"""

    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def set_resource(
        self,
        *,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
    ) -> None:
        if resource_type is not None:
            self.resource_type = resource_type
        if resource_id is not None:
            self.resource_id = resource_id

    def add_metadata(self, **metadata: Any) -> None:
        self.metadata.update(
            {key: value for key, value in metadata.items() if value is not None}
        )


class AuditService:
    """写入业务审计事件。"""

    def __init__(
        self,
        *,
        uow: AbstractUnitOfWork,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        request_context: AuditRequestContext | None = None,
    ) -> None:
        self.uow = uow
        self.session_factory = session_factory
        self.request_context = request_context or AuditRequestContext()

    async def record(
        self,
        *,
        action: AuditAction | str,
        actor_user_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        metadata: dict[str, Any] | None = None,
        independent: bool = True,
    ) -> None:
        event = AuditEvent(
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            action=str(action),
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            ip=self.request_context.ip,
            user_agent=self.request_context.user_agent,
            request_id=self.request_context.request_id,
            event_metadata=metadata or {},
        )

        if independent:
            await self._record_independent(event)
            return

        self._session.add(event)

    def capture(
        self,
        *,
        action: AuditAction | str,
        actor_user_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractAsyncContextManager[AuditCapture]:
        return _AuditCaptureContext(
            audit_service=self,
            action=action,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
        )

    async def _record_independent(self, event: AuditEvent) -> None:
        if self.session_factory is None:
            logger.warning("Audit event skipped because session_factory is unavailable")
            return

        try:
            async with self.session_factory() as session:
                session.add(event)
                await session.commit()
        except Exception:
            logger.exception("Failed to write audit event: action=%s", event.action)

    @property
    def _session(self) -> AsyncSession:
        session = getattr(self.uow, "session", None)
        if session is None:
            raise RuntimeError("AuditService requires an active UnitOfWork session.")
        return session


class _AuditCaptureContext(AbstractAsyncContextManager[AuditCapture]):
    """把上下文执行结果转换为审计 outcome。"""

    def __init__(
        self,
        *,
        audit_service: AuditService,
        action: AuditAction | str,
        actor_user_id: uuid.UUID | None,
        workspace_id: uuid.UUID | None,
        resource_type: str | None,
        resource_id: uuid.UUID | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        self.audit_service = audit_service
        self.action = action
        self.actor_user_id = actor_user_id
        self.workspace_id = workspace_id
        self.capture_state = AuditCapture(
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata.copy() if metadata else {},
        )

    async def __aenter__(self) -> AuditCapture:
        return self.capture_state

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:
        outcome = AuditOutcome.SUCCESS
        metadata = self.capture_state.metadata.copy()

        if exc is not None:
            if isinstance(exc, AppException) and exc.status_code == 403:
                outcome = AuditOutcome.DENIED
            else:
                outcome = AuditOutcome.FAILED
            metadata.setdefault("error_type", exc.__class__.__name__)
            metadata.setdefault("error_message", str(exc))

        await self.audit_service.record(
            action=self.action,
            actor_user_id=self.actor_user_id,
            workspace_id=self.workspace_id,
            resource_type=self.capture_state.resource_type,
            resource_id=self.capture_state.resource_id,
            outcome=outcome,
            metadata=metadata,
            independent=True,
        )
        return None


@asynccontextmanager
async def capture_audit(
    audit_service: object,
    **kwargs: Any,
) -> AsyncIterator[AuditCapture]:
    """兼容可选 AuditService 的审计捕获入口。"""
    if isinstance(audit_service, AuditService):
        async with audit_service.capture(**kwargs) as audit:
            yield audit
        return

    yield AuditCapture(
        resource_type=kwargs.get("resource_type"),
        resource_id=kwargs.get("resource_id"),
        metadata=(kwargs.get("metadata") or {}).copy(),
    )


async def record_audit(audit_service: object, **kwargs: Any) -> None:
    """兼容可选 AuditService 的审计记录入口。"""
    if isinstance(audit_service, AuditService):
        await audit_service.record(**kwargs)
