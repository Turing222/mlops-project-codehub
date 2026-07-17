"""Chat session and message persistence repository.

职责：封装 ChatSession 和 ChatMessage 的 CRUD、分页查询、Token 统计和幂等键去重。
边界：本模块不组装 Prompt、不调用 LLM，只做持久化读写。
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from backend.models.enums import ChatGenerationStatus, MessageStatus
from backend.models.orm.access import UserWorkspaceRole, Workspace
from backend.models.orm.chat import ChatGenerationRequest, ChatMessage, ChatSession
from backend.models.schemas.chat.context_state import ContextState
from backend.repositories.base import CRUDBase


def _generation_request_actor_scope(user_id: uuid.UUID) -> ColumnElement[bool]:
    """Require request ownership, a live session, and active tenant membership."""
    workspace_membership = exists(
        select(1)
        .select_from(UserWorkspaceRole)
        .join(Workspace, Workspace.id == UserWorkspaceRole.workspace_id)
        .where(
            UserWorkspaceRole.user_id == user_id,
            UserWorkspaceRole.workspace_id == ChatGenerationRequest.workspace_id,
            Workspace.deleted_at.is_(None),
        )
    ).correlate(ChatGenerationRequest)
    personal_scope = and_(
        ChatGenerationRequest.workspace_id.is_(None),
        ChatSession.workspace_id.is_(None),
        ChatSession.user_id == user_id,
    )
    workspace_scope = and_(
        ChatGenerationRequest.workspace_id.is_not(None),
        ChatSession.workspace_id == ChatGenerationRequest.workspace_id,
        workspace_membership,
    )
    live_session = exists(
        select(1)
        .select_from(ChatSession)
        .where(
            ChatSession.id == ChatGenerationRequest.session_id,
            ChatSession.deleted_at.is_(None),
            or_(personal_scope, workspace_scope),
        )
    ).correlate(ChatGenerationRequest)
    return and_(ChatGenerationRequest.user_id == user_id, live_session)


class ChatRepository:
    """会话和消息的持久化操作，组合两个 CRUDBase 实例管理双表。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.session_crud: CRUDBase[ChatSession, BaseModel, BaseModel] = CRUDBase(
            ChatSession, session
        )
        self.message_crud: CRUDBase[ChatMessage, BaseModel, BaseModel] = CRUDBase(
            ChatMessage, session
        )
        self.generation_request_crud: CRUDBase[
            ChatGenerationRequest, BaseModel, BaseModel
        ] = CRUDBase(ChatGenerationRequest, session)

    async def create_generation_request(
        self,
        *,
        user_id: uuid.UUID,
        client_request_id: str,
        session_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
        user_message_id: uuid.UUID | None = None,
        assistant_message_id: uuid.UUID | None = None,
        dispatch_context: dict[str, object] | None = None,
        recovery_due_at: datetime | None = None,
        reserved_credits: int = 0,
    ) -> ChatGenerationRequest:
        """Create one PREPARED durable request; the UoW owns commit/rollback."""
        return await self.generation_request_crud.create(
            obj_in={
                "user_id": user_id,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "client_request_id": client_request_id,
                "dispatch_context": dispatch_context,
                "status": ChatGenerationStatus.PREPARED,
                "attempt": 1,
                "dispatch_attempts": 0,
                "retryable": False,
                "recovery_due_at": recovery_due_at,
                "reserved_credits": reserved_credits,
            }
        )

    async def get_generation_request_for_actor(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ChatGenerationRequest | None:
        """Resolve by durable identity without exposing another actor or tenant."""
        stmt = select(ChatGenerationRequest).where(
            ChatGenerationRequest.id == request_id,
            _generation_request_actor_scope(user_id),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_generation_request_by_client_request_id_for_actor(
        self,
        *,
        user_id: uuid.UUID,
        client_request_id: str,
    ) -> ChatGenerationRequest | None:
        """Resolve an accepted request from its actor-scoped idempotency key."""
        stmt = select(ChatGenerationRequest).where(
            ChatGenerationRequest.client_request_id == client_request_id,
            _generation_request_actor_scope(user_id),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_generation_requests_for_session_for_actor(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Sequence[ChatGenerationRequest]:
        """Return request identity for messages visible to the current actor."""
        stmt = select(ChatGenerationRequest).where(
            ChatGenerationRequest.session_id == session_id,
            _generation_request_actor_scope(user_id),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_due_generation_requests(
        self,
        *,
        due_at: datetime,
        limit: int = 100,
    ) -> Sequence[ChatGenerationRequest]:
        """Return a bounded deterministic snapshot of due nonterminal requests."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        stmt = (
            select(ChatGenerationRequest)
            .where(
                ChatGenerationRequest.status.in_(
                    (
                        ChatGenerationStatus.PREPARED,
                        ChatGenerationStatus.QUEUED,
                        ChatGenerationStatus.RUNNING,
                    )
                ),
                ChatGenerationRequest.recovery_due_at.is_not(None),
                ChatGenerationRequest.recovery_due_at <= due_at,
            )
            .order_by(
                ChatGenerationRequest.recovery_due_at.asc(),
                ChatGenerationRequest.id.asc(),
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def try_queue_generation_request(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        expected_attempt: int,
        task_id: str,
        lease_token: str,
        queued_at: datetime,
        recovery_due_at: datetime,
    ) -> bool:
        """CAS PREPARED to QUEUED for the authorized current actor/attempt."""
        stmt = (
            update(ChatGenerationRequest)
            .where(
                ChatGenerationRequest.id == request_id,
                ChatGenerationRequest.status == ChatGenerationStatus.PREPARED,
                ChatGenerationRequest.attempt == expected_attempt,
                _generation_request_actor_scope(user_id),
            )
            .values(
                status=ChatGenerationStatus.QUEUED,
                task_id=task_id,
                lease_token=lease_token,
                dispatch_attempts=ChatGenerationRequest.dispatch_attempts + 1,
                queued_at=queued_at,
                recovery_due_at=recovery_due_at,
                retryable=False,
                error_code=None,
                error_message=None,
                finished_at=None,
            )
            .returning(ChatGenerationRequest.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_reserve_generation_request_redispatch(
        self,
        *,
        request_id: uuid.UUID,
        expected_attempt: int,
        task_id: str,
        lease_token: str,
        expected_dispatch_attempts: int,
        max_dispatch_attempts: int,
        due_before: datetime,
        next_recovery_due_at: datetime,
    ) -> int | None:
        """Reserve one QUEUED redispatch without creating a business attempt."""
        if expected_dispatch_attempts < 1:
            raise ValueError("expected_dispatch_attempts must be positive")
        if max_dispatch_attempts < 1:
            raise ValueError("max_dispatch_attempts must be positive")
        stmt = (
            update(ChatGenerationRequest)
            .where(
                ChatGenerationRequest.id == request_id,
                ChatGenerationRequest.status == ChatGenerationStatus.QUEUED,
                ChatGenerationRequest.attempt == expected_attempt,
                ChatGenerationRequest.task_id == task_id,
                ChatGenerationRequest.lease_token == lease_token,
                ChatGenerationRequest.dispatch_attempts == expected_dispatch_attempts,
                ChatGenerationRequest.dispatch_attempts < max_dispatch_attempts,
                ChatGenerationRequest.recovery_due_at.is_not(None),
                ChatGenerationRequest.recovery_due_at <= due_before,
            )
            .values(
                dispatch_attempts=ChatGenerationRequest.dispatch_attempts + 1,
                recovery_due_at=next_recovery_due_at,
            )
            .returning(ChatGenerationRequest.dispatch_attempts)
        )
        result = await self.session.execute(stmt)
        dispatch_attempts = result.scalar_one_or_none()
        return int(dispatch_attempts) if dispatch_attempts is not None else None

    async def try_fail_due_generation_request(
        self,
        *,
        request_id: uuid.UUID,
        expected_status: ChatGenerationStatus,
        expected_attempt: int,
        expected_dispatch_attempts: int,
        task_id: str | None,
        lease_token: str | None,
        due_before: datetime,
        finished_at: datetime,
        error_code: str,
        error_message: str,
    ) -> bool:
        """Fence one due nonterminal request into an explicit retryable failure."""
        if expected_status not in {
            ChatGenerationStatus.PREPARED,
            ChatGenerationStatus.QUEUED,
            ChatGenerationStatus.RUNNING,
        }:
            raise ValueError("expected_status must be nonterminal")
        if not error_code.strip():
            raise ValueError("error_code must not be blank")
        conditions: list[ColumnElement[bool]] = [
            ChatGenerationRequest.id == request_id,
            ChatGenerationRequest.status == expected_status,
            ChatGenerationRequest.attempt == expected_attempt,
            ChatGenerationRequest.dispatch_attempts == expected_dispatch_attempts,
            ChatGenerationRequest.recovery_due_at.is_not(None),
            ChatGenerationRequest.recovery_due_at <= due_before,
        ]
        if expected_status == ChatGenerationStatus.PREPARED:
            if task_id is not None or lease_token is not None:
                raise ValueError("a PREPARED request has no task or lease fence")
            conditions.extend(
                (
                    ChatGenerationRequest.task_id.is_(None),
                    ChatGenerationRequest.lease_token.is_(None),
                )
            )
        else:
            if task_id == "" or lease_token == "":
                raise ValueError("active request fences must not be blank")
            conditions.extend(
                (
                    ChatGenerationRequest.task_id.is_(None)
                    if task_id is None
                    else ChatGenerationRequest.task_id == task_id,
                    ChatGenerationRequest.lease_token.is_(None)
                    if lease_token is None
                    else ChatGenerationRequest.lease_token == lease_token,
                )
            )
        stmt = (
            update(ChatGenerationRequest)
            .where(*conditions)
            .values(
                status=ChatGenerationStatus.FAILED,
                retryable=True,
                error_code=error_code,
                error_message=error_message,
                recovery_due_at=None,
                finished_at=finished_at,
            )
            .returning(ChatGenerationRequest.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_claim_generation_request(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        expected_attempt: int,
        task_id: str,
        lease_token: str,
        started_at: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        """CAS QUEUED to RUNNING using the attempt lease as the worker fence."""
        stmt = (
            update(ChatGenerationRequest)
            .where(
                ChatGenerationRequest.id == request_id,
                ChatGenerationRequest.user_id == user_id,
                ChatGenerationRequest.session_id == session_id,
                ChatGenerationRequest.assistant_message_id == assistant_message_id,
                ChatGenerationRequest.status == ChatGenerationStatus.QUEUED,
                ChatGenerationRequest.attempt == expected_attempt,
                ChatGenerationRequest.task_id == task_id,
                ChatGenerationRequest.lease_token == lease_token,
            )
            .values(
                status=ChatGenerationStatus.RUNNING,
                started_at=started_at,
                heartbeat_at=started_at,
                lease_expires_at=lease_expires_at,
                recovery_due_at=lease_expires_at,
            )
            .returning(ChatGenerationRequest.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_heartbeat_generation_request(
        self,
        *,
        request_id: uuid.UUID,
        expected_attempt: int,
        lease_token: str,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        """Extend only the current RUNNING attempt's lease."""
        stmt = (
            update(ChatGenerationRequest)
            .where(
                ChatGenerationRequest.id == request_id,
                ChatGenerationRequest.status == ChatGenerationStatus.RUNNING,
                ChatGenerationRequest.attempt == expected_attempt,
                ChatGenerationRequest.lease_token == lease_token,
            )
            .values(
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
                recovery_due_at=lease_expires_at,
            )
            .returning(ChatGenerationRequest.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_finalize_generation_request(
        self,
        *,
        request_id: uuid.UUID,
        expected_attempt: int,
        lease_token: str,
        target_status: ChatGenerationStatus,
        finished_at: datetime,
        assistant_message_id: uuid.UUID | None = None,
        retryable: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """Commit a terminal outcome only from the fenced RUNNING attempt."""
        if target_status not in {
            ChatGenerationStatus.SUCCEEDED,
            ChatGenerationStatus.FAILED,
        }:
            raise ValueError("target_status must be succeeded or failed")
        if target_status == ChatGenerationStatus.SUCCEEDED:
            if retryable or error_code is not None or error_message is not None:
                raise ValueError("a succeeded request cannot carry failure details")
        elif not error_code:
            raise ValueError("a failed request requires a stable error_code")

        values: dict[str, object] = {
            "status": target_status,
            "finished_at": finished_at,
            "recovery_due_at": None,
            "retryable": (
                retryable if target_status == ChatGenerationStatus.FAILED else False
            ),
            "error_code": (
                error_code if target_status == ChatGenerationStatus.FAILED else None
            ),
            "error_message": (
                error_message if target_status == ChatGenerationStatus.FAILED else None
            ),
        }
        if assistant_message_id is not None:
            values["assistant_message_id"] = assistant_message_id

        stmt = (
            update(ChatGenerationRequest)
            .where(
                ChatGenerationRequest.id == request_id,
                ChatGenerationRequest.status == ChatGenerationStatus.RUNNING,
                ChatGenerationRequest.attempt == expected_attempt,
                ChatGenerationRequest.lease_token == lease_token,
            )
            .values(**values)
            .returning(ChatGenerationRequest.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_retry_generation_request(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        expected_attempt: int,
        dispatch_context: dict[str, object],
        recovery_due_at: datetime,
    ) -> int | None:
        """Create the next attempt only from actor-owned retryable FAILED state."""
        stmt = (
            update(ChatGenerationRequest)
            .where(
                ChatGenerationRequest.id == request_id,
                ChatGenerationRequest.status == ChatGenerationStatus.FAILED,
                ChatGenerationRequest.retryable.is_(True),
                ChatGenerationRequest.attempt == expected_attempt,
                _generation_request_actor_scope(user_id),
            )
            .values(
                status=ChatGenerationStatus.PREPARED,
                attempt=ChatGenerationRequest.attempt + 1,
                dispatch_attempts=0,
                dispatch_context=dispatch_context,
                task_id=None,
                lease_token=None,
                retryable=False,
                error_code=None,
                error_message=None,
                queued_at=None,
                started_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
                recovery_due_at=recovery_due_at,
                finished_at=None,
            )
            .returning(ChatGenerationRequest.attempt)
        )
        result = await self.session.execute(stmt)
        next_attempt = result.scalar_one_or_none()
        return int(next_attempt) if next_attempt is not None else None

    async def reset_assistant_message_for_retry(
        self,
        *,
        message_id: uuid.UUID,
    ) -> bool:
        """Clear one failed assistant message before its next fenced attempt."""
        stmt = (
            update(ChatMessage)
            .where(
                ChatMessage.id == message_id,
                ChatMessage.role == "assistant",
                ChatMessage.status == MessageStatus.FAILED,
            )
            .values(
                status=MessageStatus.THINKING,
                content="",
                latency_ms=None,
                tokens_input=0,
                tokens_output=0,
                search_context=None,
                message_metadata={},
            )
            .returning(ChatMessage.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_session(self, session_id: uuid.UUID) -> ChatSession | None:
        return await self.session_crud.get(session_id)

    async def get_context_state(self, session_id: uuid.UUID) -> ContextState:
        session = await self.get_session(session_id)
        if session is None:
            return ContextState()
        state_data = dict(session.context_state or {})
        state_data["version"] = session.context_state_version or 0
        return ContextState.model_validate(state_data)

    async def update_context_state_if_version_matches(
        self,
        *,
        session_id: uuid.UUID,
        expected_version: int,
        next_state: ContextState,
    ) -> bool:
        stmt = (
            update(ChatSession)
            .where(
                ChatSession.id == session_id,
                ChatSession.context_state_version == expected_version,
            )
            .values(
                context_state=next_state.to_storage_dict(),
                context_state_version=expected_version + 1,
            )
        )
        result = await self.session.execute(stmt)
        return getattr(result, "rowcount", 0) > 0

    async def create_session(
        self,
        user_id: uuid.UUID,
        title: str = "新对话",
        kb_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
        llm_config: dict | None = None,
    ) -> ChatSession:
        data = {
            "user_id": user_id,
            "title": title[:50] if title else "新对话",
            "kb_id": kb_id,
            "workspace_id": workspace_id,
            "llm_config": llm_config or {},
        }
        return await self.session_crud.create(obj_in=data)

    async def get_user_sessions(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> Sequence[ChatSession]:
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_user_sessions_with_total_tokens(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> list[tuple[ChatSession, int]]:
        """一次 JOIN + GROUP BY 返回会话及其总 token，避免逐会话 COUNT 的 N+1 查询。"""
        total_tokens_expr = func.coalesce(
            func.sum(ChatMessage.tokens_input + ChatMessage.tokens_output),
            0,
        ).label("total_tokens")

        stmt = (
            select(ChatSession, total_tokens_expr)
            .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.user_id == user_id)
            .group_by(ChatSession.id)
            .order_by(ChatSession.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [(row[0], int(row[1] or 0)) for row in result.all()]

    async def count_user_sessions(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ChatSession)
            .where(ChatSession.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)

    async def get_session_total_tokens(self, session_id: uuid.UUID) -> int:
        stmt = select(
            func.sum(ChatMessage.tokens_input + ChatMessage.tokens_output)
        ).where(ChatMessage.session_id == session_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_session_messages(self, session_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.session_id == session_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)

    async def get_message(self, message_id: uuid.UUID) -> ChatMessage | None:
        return await self.message_crud.get(message_id)

    async def create_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str,
        status: MessageStatus = MessageStatus.SUCCESS,
        latency_ms: int | None = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
        client_request_id: str | None = None,
        search_context: dict | None = None,
        user_id: uuid.UUID | None = None,
        message_metadata: dict | None = None,
    ) -> ChatMessage:
        data = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "status": status,
            "latency_ms": latency_ms,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "client_request_id": client_request_id,
            "search_context": search_context,
            "user_id": user_id,
            "message_metadata": message_metadata or {},
        }
        return await self.message_crud.create(obj_in=data)

    async def get_session_messages(
        self,
        session_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_message_status(
        self,
        message_id: uuid.UUID,
        status: MessageStatus,
        content: str | None = None,
        latency_ms: int | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        search_context: dict | None = None,
        message_metadata: dict | None = None,
    ) -> ChatMessage | None:
        update_data: dict[str, object] = {"status": status}
        if content is not None:
            update_data["content"] = content
        if latency_ms is not None:
            update_data["latency_ms"] = latency_ms
        if tokens_input is not None:
            update_data["tokens_input"] = tokens_input
        if tokens_output is not None:
            update_data["tokens_output"] = tokens_output
        if search_context is not None:
            update_data["search_context"] = search_context
        if message_metadata is not None:
            update_data["message_metadata"] = message_metadata

        message = await self.message_crud.get(message_id)
        if message is None:
            return None

        return await self.message_crud.update(db_obj=message, obj_in=update_data)

    async def create_thinking_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str = "",
        user_id: uuid.UUID | None = None,
    ) -> ChatMessage:
        """创建处于 thinking 状态的消息，供流式输出过程中逐步更新。"""
        return await self.create_message(
            session_id=session_id,
            role=role,
            content=content,
            status=MessageStatus.THINKING,
            user_id=user_id,
        )

    async def get_message_by_client_request_id(
        self,
        client_request_id: str,
        user_id: uuid.UUID,
    ) -> ChatMessage | None:
        """按幂等键查消息，需要 JOIN session 限定当前用户，防止跨用户碰撞。"""
        stmt = (
            select(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatMessage.client_request_id == client_request_id,
                ChatSession.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
