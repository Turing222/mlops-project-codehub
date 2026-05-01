"""Streaming chat workflow.

职责：编排流式聊天请求的幂等、会话消息、Prompt/RAG、TaskIQ 和 Redis stream 消费。
边界：本模块不实现 provider 调用细节；LLM 输出由 TaskIQ worker 发布到 Redis。
失败处理：任一阶段失败会清理幂等锁、回写助手消息失败状态，并向 SSE 输出错误事件。
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
from backend.config.llm import get_llm_model_config
from backend.core.concurrency import (
    db_concurrency_slot,
    get_db_semaphore,
    get_llm_semaphore,
)
from backend.core.config import settings
from backend.core.exceptions import AppException, app_service_error
from backend.core.redis import redis_client
from backend.core.trace_utils import (
    inject_trace_context,
    set_span_attributes,
    trace_span,
)
from backend.domain.interfaces import (
    AbstractLLMService,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.models.schemas.chat_schema import LLMQueryDTO
from backend.services.chat_service import ChatMessageUpdater, SessionManager
from backend.services.knowledge_service import DEFAULT_KNOWLEDGE_BASE_NAME
from backend.tasks.llm_tasks import generate_llm_stream_task

logger = logging.getLogger(__name__)


class ChatWorkflow:
    """流式对话编排器。"""

    @staticmethod
    def _get_llm_semaphore() -> asyncio.Semaphore:
        return get_llm_semaphore()

    @staticmethod
    def _get_db_semaphore() -> asyncio.Semaphore:
        return get_db_semaphore()

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        llm_service: AbstractLLMService,
        prompt_manager: PromptManager | None = None,
        rag_service: AbstractRAGService | None = None,
        chat_context_builder: ChatContextBuilder | None = None,
    ) -> None:
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
        """处理 SSE 流式查询请求。"""
        # Langfuse trace 需要在业务入口绑定用户和会话信息。
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

        redis = None
        lock_key: str | None = None
        trace_attrs = {
            "chat.user_id": user_id,
            "chat.session_id": session_id,
            "chat.kb_id": kb_id,
            "chat.client_request_id.present": client_request_id is not None,
            "chat.query.char_count": len(query_text),
            "chat.stream": True,
        }

        # 幂等锁避免同一 client_request_id 并发生成多条助手消息。
        with trace_span("chat.stream.idempotency_check", trace_attrs) as span:
            if client_request_id:
                redis = await redis_client.init()
                lock_key = f"idempotency:chat:{user_id}:{client_request_id}"
                is_new = await redis.set(lock_key, "PROCESSING", nx=True, ex=300)
                set_span_attributes(span, {"chat.idempotency.is_new": bool(is_new)})
                if not is_new:
                    val = await redis.get(lock_key)
                    set_span_attributes(span, {"chat.idempotency.value": val})
                    if val == "PROCESSING":
                        yield f"data: {json.dumps({'type': 'error', 'message': '正在加速计算中...'})}\n\n"
                        return
                    else:
                        yield f"data: {json.dumps({'type': 'error', 'message': '该请求已完成，请刷新页面'})}\n\n"
                        return

        # 会话和消息创建放在 DB 槽位内，避免高并发下耗尽连接池。
        with trace_span("chat.stream.create_session_and_messages", trace_attrs) as span:
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    # 悲观锁保护 token 余额检查，避免并发请求同时通过额度判断。
                    user = await self.uow.user_repo.get_with_lock(user_id)
                    if user and user.used_tokens >= user.max_tokens:
                        if redis is not None and lock_key is not None:
                            await redis.delete(lock_key)
                        yield f"data: {json.dumps({'type': 'error', 'message': 'Token 余额不足'})}\n\n"
                        return

                    session_manager = SessionManager(self.uow)
                    resolved_kb_id = kb_id
                    if session_id is None and resolved_kb_id is None:
                        default_kb = (
                            await self.uow.knowledge_repo.get_kb_by_name_for_user(
                                name=DEFAULT_KNOWLEDGE_BASE_NAME,
                                user_id=user_id,
                            )
                        )
                        if default_kb is not None:
                            resolved_kb_id = default_kb.id

                    session = await session_manager.ensure_session(
                        user_id=user_id,
                        query_text=query_text,
                        session_id=session_id,
                        kb_id=resolved_kb_id,
                    )
                    effective_kb_id = kb_id or session.kb_id
                    await session_manager.create_user_message(
                        session_id=session.id,
                        content=query_text,
                        user_id=user_id,
                    )
                    assistant_msg = await session_manager.create_assistant_message(
                        session_id=session.id,
                        client_request_id=client_request_id,
                        user_id=user_id,
                    )
            set_span_attributes(
                span,
                {
                    "chat.session_id": session.id,
                    "chat.assistant_message_id": assistant_msg.id,
                },
            )
            trace_attrs["chat.session_id"] = session.id
            trace_attrs["chat.assistant_message_id"] = assistant_msg.id

        # 历史消息和 Prompt 准备拆分，便于分别观察 DB 与 RAG/模板耗时。
        with trace_span("chat.stream.fetch_history", trace_attrs) as span:
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    session_manager = SessionManager(self.uow)
                    history_messages = await session_manager.get_session_messages(
                        session_id=session.id,
                        limit=settings.CHAT_MEMORY_FETCH_LIMIT,
                    )
            set_span_attributes(
                span, {"chat.history.message_count": len(history_messages)}
            )

        with trace_span("chat.stream.prepare_context", trace_attrs) as span:
            prepared_context = await self.chat_context_builder.build(
                history_messages=history_messages,
                current_query=query_text,
                kb_id=effective_kb_id,
            )
            assembled = prepared_context.assembled_prompt
            search_context = prepared_context.search_context
            tokens_input = assembled.total_tokens
            set_span_attributes(
                span,
                {
                    "chat.prompt.tokens_input": tokens_input,
                    "chat.prompt.message_count": len(assembled.messages),
                    "chat.prompt.uses_rag": search_context is not None,
                    "rag.hit_count": len(search_context["chunks"])
                    if search_context
                    else 0,
                },
            )

        # 先发送 meta，让前端尽早拿到会话和消息 id。
        meta_event = json.dumps(
            {
                "type": "meta",
                "session_id": str(session.id),
                "session_title": session.title,
                "message_id": str(assistant_msg.id),
            }
        )
        yield f"data: {meta_event}\n\n"

        llm_query = LLMQueryDTO(
            session_id=session.id,
            query_text=query_text,
            conversation_history=assembled.messages,
        )

        task_id = str(uuid.uuid4())
        channel = f"stream:{task_id}"

        pubsub = None
        try:
            with trace_span(
                "chat.stream.dispatch_task",
                {**trace_attrs, "task.id": task_id, "redis.channel": channel},
            ):
                # 必须先订阅后投递，避免 worker 首包发布过快导致丢消息。
                pubsub = (await redis_client.init()).pubsub()
                await pubsub.subscribe(channel)
                await generate_llm_stream_task.kiq(
                    llm_query.model_dump(mode="json"),
                    channel,
                    inject_trace_context(),
                )
        except AppException as exc:
            if redis is not None and lock_key is not None:
                await redis.delete(lock_key)
            logger.warning("流式任务初始化失败: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            yield "data: [DONE]\n\n"
            return
        except Exception as exc:
            if redis is not None and lock_key is not None:
                await redis.delete(lock_key)
            logger.error("流式任务初始化异常: %s", str(exc), exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': '服务暂时不可用，请稍后重试'})}\n\n"
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            yield "data: [DONE]\n\n"
            return

        accumulated_content = []
        done_received = False
        stream_iter = pubsub.listen()

        def _read_stream_payload(message: dict) -> str | None:
            if message.get("type") != "message":
                return None
            data = message.get("data")
            if isinstance(data, bytes):
                return data.decode("utf-8")
            if isinstance(data, str):
                return data
            return None

        try:
            with trace_span(
                "chat.stream.consume_worker_stream",
                {**trace_attrs, "task.id": task_id, "redis.channel": channel},
            ) as span:
                loop = asyncio.get_running_loop()
                deadline = (
                    loop.time() + settings.CHAT_STREAM_FIRST_MESSAGE_TIMEOUT_SECONDS
                )
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise app_service_error(
                            "LLM 响应超时，请稍后重试", code="LLM_TIMEOUT"
                        )
                    try:
                        first_message = await asyncio.wait_for(
                            anext(stream_iter),
                            timeout=remaining,
                        )
                    except TimeoutError as exc:
                        raise app_service_error(
                            "LLM 响应超时，请稍后重试", code="LLM_TIMEOUT"
                        ) from exc
                    except StopAsyncIteration as exc:
                        raise app_service_error(
                            "LLM 流式通道异常结束",
                            code="LLM_STREAM_CHANNEL_CLOSED",
                        ) from exc

                    first_payload = _read_stream_payload(first_message)
                    if first_payload is None:
                        continue
                    if first_payload == "[DONE]":
                        done_received = True
                    elif first_payload.startswith("[ERROR]"):
                        raise app_service_error(
                            f"Taskiq 队列执行 LLM 错误: {first_payload[7:]}",
                            code="LLM_TASK_FAILED",
                        )
                    else:
                        accumulated_content.append(first_payload)
                        first_chunk = json.dumps(
                            {"type": "chunk", "content": first_payload}
                        )
                        yield f"data: {first_chunk}\n\n"
                    break

                if not done_received:
                    async for message in stream_iter:
                        payload = _read_stream_payload(message)
                        if payload is None:
                            continue
                        if payload == "[DONE]":
                            done_received = True
                            break
                        if payload.startswith("[ERROR]"):
                            raise app_service_error(
                                f"Taskiq 队列执行 LLM 错误: {payload[7:]}",
                                code="LLM_TASK_FAILED",
                            )
                        accumulated_content.append(payload)
                        chunk_event = json.dumps({"type": "chunk", "content": payload})
                        yield f"data: {chunk_event}\n\n"

                if not done_received:
                    raise app_service_error(
                        "LLM 流式响应中断，请稍后重试",
                        code="LLM_STREAM_INTERRUPTED",
                    )
                set_span_attributes(
                    span,
                    {
                        "llm.response.chunk_count": len(accumulated_content),
                        "llm.response.char_count": sum(
                            len(chunk) for chunk in accumulated_content
                        ),
                        "llm.stream.done_received": done_received,
                    },
                )
        except AppException as exc:
            if redis is not None and lock_key is not None:
                await redis.delete(lock_key)
            logger.warning("流式 LLM 调用业务异常: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            yield "data: [DONE]\n\n"
            return
        except Exception as exc:
            if redis is not None and lock_key is not None:
                await redis.delete(lock_key)
            logger.error("流式 LLM 调用异常: %s", str(exc), exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': '服务暂时不可用，请稍后重试'})}\n\n"
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            yield "data: [DONE]\n\n"
            return
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                except Exception:
                    logger.debug(
                        "Redis 取消订阅失败: channel=%s", channel, exc_info=True
                    )

                close_coro = getattr(pubsub, "aclose", None)
                if close_coro is not None:
                    await close_coro()
                else:
                    close_fn = getattr(pubsub, "close", None)
                    if close_fn is not None:
                        maybe_awaitable = close_fn()
                        if asyncio.iscoroutine(maybe_awaitable):
                            await maybe_awaitable

        # 流消费完成后再持久化完整答案，避免写入半截成功消息。
        full_content = "".join(accumulated_content)
        model_name = getattr(
            self.llm_service,
            "model_name",
            get_llm_model_config().resolve_profile().model,
        )
        tokens_output = count_tokens(full_content, model_name)

        with trace_span("chat.stream.finalize_message", trace_attrs) as span:
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_success(
                        message_id=assistant_msg.id,
                        content=full_content,
                        tokens_input=tokens_input,
                        tokens_output=tokens_output,
                        search_context=search_context,
                    )
                    # token 累加使用条件更新，避免并发完成时突破用户额度上限。
                    total_tokens = tokens_input + tokens_output
                    ok = await self.uow.user_repo.increment_used_tokens_guarded(
                        user_id, total_tokens
                    )
                    if not ok:
                        logger.warning(
                            "Token 累加后超出上限，本次消耗未记录: user_id=%s, delta=%d",
                            user_id,
                            total_tokens,
                        )
            set_span_attributes(
                span,
                {
                    "chat.tokens_input": tokens_input,
                    "chat.tokens_output": tokens_output,
                    "llm.response.char_count": len(full_content),
                },
            )

        if redis is not None and lock_key is not None:
            await redis.set(lock_key, str(assistant_msg.id), ex=3600)

        yield "data: [DONE]\n\n"
