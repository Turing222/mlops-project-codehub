"""
Chat Workflow — 处理对话业务流程

编排者角色：
1. 从 DB 查询会话与历史消息
2. 调用 PromptManager 组装完整的消息列表
3. 发给 LLMService 获取回复
4. 将结果存入 DB
"""

from collections.abc import AsyncGenerator

import asyncio
import logging
import uuid
import json
import time

from backend.core.config import settings
from backend.core.exceptions import ServiceError, ValidationError
from backend.core.redis import redis_client
from backend.domain.interfaces import AbstractLLMService
from backend.models.orm.chat import MessageStatus
from backend.models.schemas.chat_schema import (
    ChatQueryResponse,
    LLMQueryDTO,
    MessageResponse,
)
from backend.services.chat_service import ChatMessageUpdater, SessionManager
from backend.services.llm_core import PromptManager
from backend.services.unit_of_work import AbstractUnitOfWork
from backend.utils.tokenizer import count_messages_tokens, count_tokens

logger = logging.getLogger(__name__)


class ChatWorkflow:
    # 类级别信号量，通过 Property 延迟初始化，解决 asyncio 在不同线程/无 Loop 环境下的初始化问题
    _llm_semaphore: asyncio.Semaphore | None = None
    _db_semaphore: asyncio.Semaphore | None = None

    @classmethod
    def _get_llm_semaphore(cls) -> asyncio.Semaphore:
        if cls._llm_semaphore is None:
            cls._llm_semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)
        return cls._llm_semaphore

    @classmethod
    def _get_db_semaphore(cls) -> asyncio.Semaphore:
        if cls._db_semaphore is None:
            cls._db_semaphore = asyncio.Semaphore(settings.DB_MAX_CONCURRENCY)
        return cls._db_semaphore

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        llm_service: AbstractLLMService,
        prompt_manager: PromptManager | None = None,
    ):
        self.uow = uow
        self.llm_service = llm_service
        self.prompt_manager = prompt_manager or PromptManager()

    def _history_to_dicts(self, messages) -> list[dict]:
        """将 ORM 消息对象转换为 PromptManager 所需的字典列表"""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
            if msg.role in ("user", "assistant") and msg.content
        ]

    async def handle_query(
        self,
        user_id: uuid.UUID,
        query_text: str,
        session_id: uuid.UUID | None = None,
        kb_id: uuid.UUID | None = None,
        client_request_id: str | None = None,
    ) -> ChatQueryResponse:
        """
        处理用户查询请求 (非流式)。
        """
        logger.info(
            "Workflow 收到查询: user_id=%s, session_id=%s, query_len=%d",
            user_id,
            session_id,
            len(query_text),
        )

        # 0. 幂等校验
        if client_request_id:
            redis = await redis_client.init()
            lock_key = f"idempotency:chat:{client_request_id}"
            is_new = await redis.set(lock_key, "PROCESSING", nx=True, ex=300)
            if not is_new:
                val = await redis.get(lock_key)
                if val == "PROCESSING":
                    raise ServiceError("正在加速计算中...", details={"client_request_id": client_request_id})
                else:
                    async with self.uow:
                        msg = await self.uow.chat_repo.get_message_by_client_request_id(client_request_id)
                        if msg and msg.status == MessageStatus.SUCCESS:
                            session = await self.uow.chat_repo.get_session(msg.session_id)
                            return ChatQueryResponse(
                                session_id=session.id,
                                session_title=session.title,
                                answer=MessageResponse.model_validate(msg),
                            )

        # 1. 确认或创建会话
        async with self._get_db_semaphore():
            async with self.uow:
                # 校验 Token 余额
                user = await self.uow.users.get(user_id)
                if user and user.used_tokens >= user.max_tokens:
                    if client_request_id: await redis.delete(lock_key)
                    raise ValidationError("Token 余额不足", details={"used": user.used_tokens, "max": user.max_tokens})

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
                    client_request_id=client_request_id,
                )

        # 4. 查询历史消息并组装 Prompt
        async with self._get_db_semaphore():
            async with self.uow:
                session_manager = SessionManager(self.uow)
                history_messages = await session_manager.get_session_messages(
                    session_id=session.id,
                )

        history_dicts = self._history_to_dicts(history_messages)
        assembled = self.prompt_manager.assemble(history_dicts, query_text)
        tokens_input = assembled.total_tokens

        # 5. 调用 LLM
        llm_query = LLMQueryDTO(
            session_id=session.id,
            query_text=query_text,
            conversation_history=assembled.messages,
        )

        try:
            async with self._get_llm_semaphore():
                result = await self.llm_service.generate_response(llm_query)
        except Exception as e:
            if client_request_id: await redis.delete(lock_key)
            async with self._get_db_semaphore():
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            raise

        if not result.success:
            if client_request_id: await redis.delete(lock_key)
            async with self._get_db_semaphore():
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(
                        assistant_msg.id,
                        error_content=result.error_message or "LLM 服务调用失败",
                    )
            raise ServiceError("LLM 服务返回失败", details={"error": result.error_message})

        # 6. 更新助手消息并累加 Token
        async with self._get_db_semaphore():
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                updated_msg = await updater.update_as_success(
                    message_id=assistant_msg.id,
                    content=result.content,
                    tokens_input=tokens_input,
                    tokens_output=result.completion_tokens,
                )
                await self.uow.users.increment_used_tokens(
                    user_id, tokens_input + (result.completion_tokens or 0)
                )
        
        if client_request_id:
            await redis.set(lock_key, str(updated_msg.id), ex=3600)

        return ChatQueryResponse(
            session_id=session.id,
            session_title=session.title,
            answer=MessageResponse.model_validate(updated_msg),
        )

    async def handle_query_stream(
        self,
        user_id: uuid.UUID,
        query_text: str,
        session_id: uuid.UUID | None = None,
        kb_id: uuid.UUID | None = None,
        client_request_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        处理流式查询请求 (含幂等、Token 管理)
        """
        logger.info(
            "Workflow 流式查询开始: user_id=%s, session_id=%s, query_len=%d",
            user_id,
            session_id,
            len(query_text),
        )

        # 0. 幂等校验
        if client_request_id:
            redis = await redis_client.init()
            lock_key = f"idempotency:chat:{client_request_id}"
            is_new = await redis.set(lock_key, "PROCESSING", nx=True, ex=300)
            if not is_new:
                val = await redis.get(lock_key)
                if val == "PROCESSING":
                    yield f"data: {json.dumps({'type': 'error', 'message': '正在加速计算中...'})}\n\n"
                    return
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': '该请求已完成，请刷新页面'})}\n\n"
                    return

        # 1. 确认或创建会话 + 保存用户消息 + 创建助手消息占位
        async with self._get_db_semaphore():
            async with self.uow:
                # 校验 Token 余额
                user = await self.uow.users.get(user_id)
                if user and user.used_tokens >= user.max_tokens:
                    if client_request_id: await redis.delete(lock_key)
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Token 余额不足'})}\n\n"
                    return

                session_manager = SessionManager(self.uow)
                session = await session_manager.ensure_session(
                    user_id=user_id,
                    query_text=query_text,
                    session_id=session_id,
                    kb_id=kb_id,
                )
                await session_manager.create_user_message(
                    session_id=session.id,
                    content=query_text,
                )
                assistant_msg = await session_manager.create_assistant_message(
                    session_id=session.id,
                    client_request_id=client_request_id,
                )

        # 2. 查询历史消息并组装 Prompt
        async with self._get_db_semaphore():
            async with self.uow:
                session_manager = SessionManager(self.uow)
                history_messages = await session_manager.get_session_messages(
                    session_id=session.id,
                )

        history_dicts = self._history_to_dicts(history_messages)
        assembled = self.prompt_manager.assemble(history_dicts, query_text)
        tokens_input = assembled.total_tokens

        # 3. 发送 meta 事件
        meta_event = json.dumps({
            "type": "meta",
            "session_id": str(session.id),
            "session_title": session.title,
            "message_id": str(assistant_msg.id),
        })
        yield f"data: {meta_event}\n\n"

        # 4. 流式调用 LLM
        llm_query = LLMQueryDTO(
            session_id=session.id,
            query_text=query_text,
            conversation_history=assembled.messages,
        )

        accumulated_content = []
        start_time = time.time()
        try:
            async with self._get_llm_semaphore():
                async for chunk in self.llm_service.stream_response(llm_query):
                    accumulated_content.append(chunk)
                    chunk_event = json.dumps({"type": "chunk", "content": chunk})
                    yield f"data: {chunk_event}\n\n"
        except Exception as e:
            if client_request_id: await redis.delete(lock_key)
            logger.error("流式 LLM 调用失败: %s", str(e), exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            async with self._get_db_semaphore():
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            yield "data: [DONE]\n\n"
            return

        # 5. 更新助手消息并累加 Token
        full_content = "".join(accumulated_content)
        tokens_output = count_tokens(full_content)
        
        async with self._get_db_semaphore():
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_success(
                    message_id=assistant_msg.id,
                    content=full_content,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                )
                await self.uow.users.increment_used_tokens(
                    user_id, tokens_input + tokens_output
                )
        
        if client_request_id:
            await redis.set(lock_key, str(assistant_msg.id), ex=3600)

        yield "data: [DONE]\n\n"
