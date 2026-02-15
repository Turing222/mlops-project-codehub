"""
Chat Workflow — 处理对话业务流程
"""

import logging
import uuid
from typing import Optional

from backend.core.exceptions import ServiceError
from backend.models.schemas.chat_schema import (
    ChatQueryResponse,
    LLMQueryDTO,
    MessageResponse,
)
from backend.services.chat_service import ChatMessageUpdater, SessionManager
from backend.domain.interfaces import AbstractLLMService
from backend.services.unit_of_work import AbstractUnitOfWork

logger = logging.getLogger(__name__)


class ChatWorkflow:
    def __init__(
        self,
        uow: AbstractUnitOfWork,
        llm_service: AbstractLLMService,
    ):
        self.uow = uow
        self.llm_service = llm_service

    async def handle_query(
        self,
        user_id: uuid.UUID,
        query_text: str,
        session_id: uuid.UUID | None = None,
        kb_id: uuid.UUID | None = None,
    ) -> ChatQueryResponse:
        """
        处理用户查询请求。

        流程：
        1. 确认/创建会话
        2. 保存用户消息
        3. 创建助手消息占位（thinking 状态）
        4. 调用 LLM 获取回复
        5. 更新助手消息为成功/失败状态
        """
        logger.info(
            "Workflow 收到查询: user_id=%s, session_id=%s, query_len=%d",
            user_id,
            session_id,
            len(query_text),
        )

        # 1. 确认或创建会话
        async with self.uow:
            session_manager = SessionManager(self.uow)
            session = await session_manager.ensure_session(
                user_id=user_id,
                query_text=query_text,
                session_id=session_id,
                kb_id=kb_id,
            )
            # 2. 保存用户消息
            await session_manager.create_user_message(
                session_id=session.id,
                content=query_text,
            )
            # 3. 创建助手消息占位
            assistant_msg = await session_manager.create_assistant_message(
                session_id=session.id,
            )

        # 4. 调用 LLM
        llm_query = LLMQueryDTO(
            session_id=session.id,
            query_text=query_text,
        )

        try:
            result = await self.llm_service.generate_response(llm_query)
        except ServiceError:
            # LLM 失败时更新消息状态
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_failed(assistant_msg.id)
            raise

        if not result.success:
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_failed(
                    assistant_msg.id,
                    error_content=result.error_message or "LLM 服务调用失败",
                )
            raise ServiceError(
                "LLM 服务返回失败",
                details={"session_id": str(session.id), "error": result.error_message},
            )

        # 5. 更新助手消息为成功状态
        async with self.uow:
            updater = ChatMessageUpdater(self.uow)
            updated_msg = await updater.update_as_success(
                message_id=assistant_msg.id,
                content=result.content,
            )

        logger.info(
            "Workflow 处理完成: session_id=%s, message_id=%s, latency_ms=%s",
            session.id,
            updated_msg.id,
            result.latency_ms,
        )

        return ChatQueryResponse(
            session_id=session.id,
            session_title=session.title,
            answer=MessageResponse.model_validate(updated_msg),
        )
