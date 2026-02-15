"""
Chat Service — 会话管理与消息更新

企业级设计：
- SessionManager: 会话生命周期管理（创建、查询、验证权限）
- ChatMessageUpdater: 消息状态机（thinking → streaming → success/failed）
"""

import logging
import time
import uuid

from backend.core.exceptions import ResourceNotFound, ServiceError, ValidationError
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.chat import ChatMessage, ChatSession, MessageStatus
from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO
from backend.services.base import BaseService

logger = logging.getLogger(__name__)


class SessionManager(BaseService[AbstractUnitOfWork]):
    """会话管理器：确认或创建会话，创建用户消息"""

    def __init__(self, uow: AbstractUnitOfWork):
        super().__init__(uow)

    async def ensure_session(
        self,
        user_id: uuid.UUID,
        query_text: str,
        session_id: uuid.UUID | None = None,
        kb_id: uuid.UUID | None = None,
    ) -> ChatSession:
        """
        确认或创建会话

        Args:
            user_id: 用户 ID
            query_text: 用户问题（用于生成新会话标题）
            session_id: 会话 ID，None 则创建新会话
            kb_id: 知识库 ID，可选

        Returns:
            ChatSession 对象

        Raises:
            ResourceNotFound: 会话不存在
            ValidationError: 无权访问该会话
        """
        if session_id:
            session = await self.uow.chat_repo.get_session(session_id)
            if not session:
                logger.warning("会话不存在: session_id=%s, user_id=%s", session_id, user_id)
                raise ResourceNotFound(
                    f"会话不存在: {session_id}",
                    details={"session_id": str(session_id)},
                )
            if session.user_id != user_id:
                logger.warning(
                    "用户无权访问会话: session_id=%s, owner=%s, requester=%s",
                    session_id, session.user_id, user_id,
                )
                raise ValidationError(
                    "无权访问该会话",
                    details={"session_id": str(session_id)},
                )
            logger.debug("继续已有会话: session_id=%s", session_id)
            return session

        # 创建新会话，标题取问题前 50 字符
        title = query_text.strip()[:50] if query_text else "新对话"
        session = await self.uow.chat_repo.create_session(
            user_id=user_id,
            title=title,
            kb_id=kb_id,
        )
        logger.info("创建新会话: session_id=%s, title=%s, user_id=%s", session.id, title, user_id)
        return session

    async def create_user_message(
        self,
        session_id: uuid.UUID,
        content: str,
    ) -> ChatMessage:
        """
        创建用户消息

        Args:
            session_id: 会话 ID
            content: 消息内容

        Returns:
            ChatMessage 对象
        """
        message = await self.uow.chat_repo.create_message(
            session_id=session_id,
            role="user",
            content=content.strip(),
            status=MessageStatus.SUCCESS,
        )
        logger.debug("创建用户消息: message_id=%s, session_id=%s", message.id, session_id)
        return message

    async def create_assistant_message(
        self,
        session_id: uuid.UUID,
        status: MessageStatus = MessageStatus.THINKING,
    ) -> ChatMessage:
        """
        创建助手消息（初始状态为思考中）

        Args:
            session_id: 会话 ID
            status: 消息状态，默认为 THINKING

        Returns:
            ChatMessage 对象
        """
        message = await self.uow.chat_repo.create_message(
            session_id=session_id,
            role="assistant",
            content="",
            status=status,
        )
        logger.debug("创建助手消息: message_id=%s, session_id=%s", message.id, session_id)
        return message

    async def get_session(self, session_id: uuid.UUID) -> ChatSession | None:
        """获取会话详情"""
        return await self.uow.chat_repo.get_session(session_id)

    async def get_user_sessions(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> list[ChatSession]:
        """获取用户的会话列表"""
        sessions = await self.uow.chat_repo.get_user_sessions(
            user_id=user_id,
            skip=skip,
            limit=limit,
        )
        logger.debug("获取用户会话列表: user_id=%s, count=%d", user_id, len(sessions))
        return list(sessions)

    async def get_session_messages(
        self,
        session_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ChatMessage]:
        """获取会话的消息列表"""
        messages = await self.uow.chat_repo.get_session_messages(
            session_id=session_id,
            skip=skip,
            limit=limit,
        )
        logger.debug("获取会话消息: session_id=%s, count=%d", session_id, len(messages))
        return list(messages)


class ChatMessageUpdater(BaseService[AbstractUnitOfWork]):
    """
    聊天消息更新器：调用 LLM API 后的状态更新

    状态机: THINKING → STREAMING → SUCCESS / FAILED
    """

    def __init__(self, uow: AbstractUnitOfWork):
        super().__init__(uow)

    async def update_as_success(
        self,
        message_id: uuid.UUID,
        content: str,
        start_time: float | None = None,
    ) -> ChatMessage:
        """
        更新消息为成功状态

        Args:
            message_id: 消息 ID
            content: 完整的响应内容
            start_time: 开始时间（用于计算延迟），可选

        Returns:
            更新后的 ChatMessage 对象

        Raises:
            ResourceNotFound: 消息不存在
        """
        latency_ms = None
        if start_time:
            latency_ms = int((time.time() - start_time) * 1000)

        message = await self.uow.chat_repo.update_message_status(
            message_id=message_id,
            status=MessageStatus.SUCCESS,
            content=content,
            latency_ms=latency_ms,
        )
        if not message:
            logger.error("更新消息失败，消息不存在: message_id=%s", message_id)
            raise ResourceNotFound(
                f"消息不存在: {message_id}",
                details={"message_id": str(message_id)},
            )
        logger.info(
            "消息更新成功: message_id=%s, latency_ms=%s",
            message_id, latency_ms,
        )
        return message

    async def update_as_failed(
        self,
        message_id: uuid.UUID,
        error_content: str = "抱歉，处理您的请求时出现错误。",
    ) -> ChatMessage | None:
        """
        更新消息为失败状态

        Args:
            message_id: 消息 ID
            error_content: 错误提示内容

        Returns:
            更新后的 ChatMessage 对象，消息不存在时返回 None
        """
        message = await self.uow.chat_repo.update_message_status(
            message_id=message_id,
            status=MessageStatus.FAILED,
            content=error_content,
        )
        if message:
            logger.warning("消息更新为失败状态: message_id=%s", message_id)
        else:
            logger.error("更新失败状态时消息不存在: message_id=%s", message_id)
        return message

    async def update_as_streaming(
        self,
        message_id: uuid.UUID,
        content: str,
    ) -> ChatMessage | None:
        """
        更新消息为流式输出中状态

        Args:
            message_id: 消息 ID
            content: 当前累积的内容

        Returns:
            更新后的 ChatMessage 对象
        """
        return await self.uow.chat_repo.update_message_status(
            message_id=message_id,
            status=MessageStatus.STREAMING,
            content=content,
        )
