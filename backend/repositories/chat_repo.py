"""Chat session and message persistence repository.

职责：封装 ChatSession 和 ChatMessage 的 CRUD、分页查询、Token 统计和幂等键去重。
边界：本模块不组装 Prompt、不调用 LLM，只做持久化读写。
"""

import uuid
from collections.abc import Sequence

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import MessageStatus
from backend.models.orm.chat import ChatMessage, ChatSession
from backend.models.schemas.chat.context_state import ContextState
from backend.repositories.base import CRUDBase


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
