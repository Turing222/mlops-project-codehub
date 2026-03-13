"""
Chat Workflow — 处理对话业务流程

编排者角色：
1. 从 DB 查询会话与历史消息
2. 调用 PromptManager 组装完整的消息列表
3. 发给 LLMService 获取回复
4. 将结果存入 DB
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator

from langfuse import get_client, observe

from backend.ai.core import PromptManager
from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.ai.core.token_counter import count_tokens
from backend.core.config import settings
from backend.core.exceptions import ServiceError
from backend.core.redis import redis_client
from backend.domain.interfaces import AbstractLLMService, AbstractRAGService
from backend.models.schemas.chat_schema import LLMQueryDTO
from backend.services.chat_service import ChatMessageUpdater, SessionManager
from backend.services.unit_of_work import AbstractUnitOfWork
from backend.tasks.llm_tasks import generate_llm_stream_task

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
        rag_service: AbstractRAGService | None = None,
        chat_context_builder: ChatContextBuilder | None = None,
    ):
        self.uow = uow
        self.llm_service = llm_service
        self.chat_context_builder = chat_context_builder or ChatContextBuilder(
            prompt_manager=prompt_manager,
            rag_service=rag_service,
        )

    @observe()
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
        # 绑定当前追踪的上下文信息
        get_client().update_current_trace(
            user_id=str(user_id),
            session_id=str(session_id) if session_id else None,
            tags=["chat_api", "stream"],
        )
        logger.info(
            "Workflow 流式查询开始: user_id=%s, session_id=%s, query_len=%d",
            user_id,
            session_id,
            len(query_text),
        )

        # 0. 幂等校验
        if client_request_id:
            redis = await redis_client.init()
            lock_key = f"idempotency:chat:{user_id}:{client_request_id}"
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
                    if client_request_id:
                        await redis.delete(lock_key)
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
                    limit=settings.CHAT_MEMORY_FETCH_LIMIT,
                )

        prepared_context = await self.chat_context_builder.build(
            history_messages=history_messages,
            current_query=query_text,
            kb_id=kb_id,
        )
        assembled = prepared_context.assembled_prompt
        search_context = prepared_context.search_context
        tokens_input = assembled.total_tokens

        # 3. 发送 meta 事件
        meta_event = json.dumps(
            {
                "type": "meta",
                "session_id": str(session.id),
                "session_title": session.title,
                "message_id": str(assistant_msg.id),
            }
        )
        yield f"data: {meta_event}\n\n"

        # 4. 改为 Taskiq 异步队列排队与 Redis Pub/Sub 接收流

        llm_query = LLMQueryDTO(
            session_id=session.id,
            query_text=query_text,
            conversation_history=assembled.messages,
        )

        task_id = str(uuid.uuid4())
        channel = f"stream:{task_id}"

        # 触发队列任务
        await generate_llm_stream_task.kiq(llm_query.model_dump(mode="json"), channel)

        # 监听 Redis 频道
        redis = await redis_client.init()
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)

        accumulated_content = []
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")

                    if data == "[DONE]":
                        break
                    elif data.startswith("[ERROR]"):
                        raise ServiceError(f"Taskiq 队列执行 LLM 错误: {data[7:]}")
                    else:
                        accumulated_content.append(data)
                        chunk_event = json.dumps({"type": "chunk", "content": data})
                        yield f"data: {chunk_event}\n\n"
        except Exception as e:
            if client_request_id:
                await redis.delete(lock_key)
            logger.error("流式 LLM 调用异常: %s", str(e), exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            async with self._get_db_semaphore():
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            yield "data: [DONE]\n\n"
            return
        finally:
            await pubsub.unsubscribe()

        # 5. 更新助手消息并累加 Token
        full_content = "".join(accumulated_content)
        tokens_output = count_tokens(full_content, settings.LLM_MODEL_NAME)

        async with self._get_db_semaphore():
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_success(
                    message_id=assistant_msg.id,
                    content=full_content,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    search_context=search_context,
                )
                await self.uow.users.increment_used_tokens(
                    user_id, tokens_input + tokens_output
                )

        if client_request_id:
            await redis.set(lock_key, str(assistant_msg.id), ex=3600)

        yield "data: [DONE]\n\n"
