import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.chat import ChatMessage, ChatSession, MessageStatus
from backend.repositories.base import CRUDBase


class ChatRepository:
    """聊天相关的 Repository，包含 Session 和 Message 的操作"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.session_crud = CRUDBase(ChatSession, session)
        self.message_crud = CRUDBase(ChatMessage, session)

    # ========== ChatSession 操作 ==========

    async def get_session(self, session_id: uuid.UUID) -> ChatSession | None:
        """根据 ID 获取会话"""
        return await self.session_crud.get(session_id)

    async def create_session(
        self,
        user_id: uuid.UUID,
        title: str = "新对话",
        kb_id: uuid.UUID | None = None,
        model_config: dict | None = None,
    ) -> ChatSession:
        """创建新会话"""
        data = {
            "user_id": user_id,
            "title": title[:50] if title else "新对话",  # 限制长度
            "kb_id": kb_id,
            "model_config": model_config or {},
        }
        return await self.session_crud.create(obj_in=data)

    async def get_user_sessions(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> Sequence[ChatSession]:
        """获取用户的会话列表"""
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_session_total_tokens(self, session_id: uuid.UUID) -> int:
        """计算会话消耗的总 Token 数"""
        from sqlalchemy import func
        stmt = select(func.sum(ChatMessage.tokens_input + ChatMessage.tokens_output)).where(
            ChatMessage.session_id == session_id
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    # ========== ChatMessage 操作 ==========

    async def get_message(self, message_id: uuid.UUID) -> ChatMessage | None:
        """根据 ID 获取消息"""
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
    ) -> ChatMessage:
        """创建新消息"""
        data = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "status": status,
            "latency_ms": latency_ms,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "client_request_id": client_request_id,
        }
        return await self.message_crud.create(obj_in=data)

    async def get_session_messages(
        self,
        session_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[ChatMessage]:
        """获取会话的消息列表，按创建时间正序排列"""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
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
    ) -> ChatMessage | None:
        """更新消息状态和内容"""
        message = await self.get_message(message_id)
        if not message:
            return None

        update_data = {"status": status}
        if content is not None:
            update_data["content"] = content
        if latency_ms is not None:
            update_data["latency_ms"] = latency_ms
        if tokens_input is not None:
            update_data["tokens_input"] = tokens_input
        if tokens_output is not None:
            update_data["tokens_output"] = tokens_output

        return await self.message_crud.update(db_obj=message, obj_in=update_data)

    async def create_thinking_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str = "",
    ) -> ChatMessage:
        """创建正在思考中的消息（用于流式输出）"""
        return await self.create_message(
            session_id=session_id,
            role=role,
            content=content,
            status=MessageStatus.THINKING,
        )

    async def get_message_by_client_request_id(self, client_request_id: str) -> ChatMessage | None:
        """根据客户端请求 ID 获取消息"""
        stmt = select(ChatMessage).where(ChatMessage.client_request_id == client_request_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
