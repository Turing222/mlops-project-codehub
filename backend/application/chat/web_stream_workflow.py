"""Streaming chat workflow.

职责：编排流式聊天请求的幂等、会话消息、TaskIQ 和 Redis stream 转发。
边界：本模块不实现 provider/RAG/Prompt 细节；LLM 输出由 TaskIQ worker 发布到 Redis。
失败处理：任务投递前失败由 Web 回写；任务投递后最终消息状态由 worker 拥有。
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator

import redis.asyncio as redis

from backend.application.chat.session_orchestrator import ChatSessionOrchestrator
from backend.application.chat.stream_events import (
    SSEEvent,
    chunk_event,
    decode_stream_event,
    done_event,
    error_event,
    meta_event,
)
from backend.application.chat.timing import elapsed_ms, merge_metrics, perf_start
from backend.config.settings import settings
from backend.contracts.interfaces import (
    AbstractTaskDispatcher,
    AbstractUnitOfWork,
)
from backend.core.concurrency import db_concurrency_slot
from backend.core.exceptions import AppException, app_service_error
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.observability.langfuse_utils import set_langfuse_trace_metadata
from backend.observability.trace_utils import (
    inject_trace_context,
    set_span_attributes,
    trace_span,
)
from backend.services.chat_service import ChatMessageUpdater, SessionManager
from backend.services.feature_flag_service import FeatureFlagService
from backend.services.permission_service import PermissionService

logger = logging.getLogger(__name__)


class ChatWorkflow:
    """流式对话编排器。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        dispatcher: AbstractTaskDispatcher,
        redis_client: redis.Redis,
        permission_service: PermissionService,
        feature_flag_service: FeatureFlagService,
        session_manager: SessionManager | None = None,
    ) -> None:
        self.uow = uow
        self.dispatcher = dispatcher
        self.redis = redis_client
        self.permission_service = permission_service
        self._feature_flag_service = feature_flag_service
        self._session_manager = session_manager or SessionManager(
            uow, permission_service
        )

    async def handle_query_stream(
        self,
        command: ChatQueryCommand,
    ) -> AsyncGenerator[SSEEvent, None]:
        """处理 SSE 流式查询请求。"""
        with set_langfuse_trace_metadata(
            user_id=command.user_id,
            session_id=command.session_id,
            tags=["chat_api", "stream"],
        ):
            async for event in self._handle_query_stream(command):
                yield event

    async def _handle_query_stream(
        self,
        command: ChatQueryCommand,
    ) -> AsyncGenerator[SSEEvent, None]:
        user_id = command.user_id
        query_text = command.query_text
        session_id = command.session_id
        kb_id = command.kb_id
        client_request_id = command.client_request_id
        request_started = perf_start()
        logger.info(
            "Workflow 流式查询开始: user_id=%s, session_id=%s, query_len=%d",
            user_id,
            session_id,
            len(query_text),
        )

        trace_attrs = {
            "chat.user_id": user_id,
            "chat.session_id": session_id,
            "chat.kb_id": kb_id,
            "chat.client_request_id.present": client_request_id is not None,
            "chat.query.char_count": len(query_text),
            "chat.stream": True,
        }

        # 幂等锁避免同一 client_request_id 并发生成多条助手消息。
        orchestrator = ChatSessionOrchestrator(
            self.uow,
            self.redis,
            self.permission_service,
            self._feature_flag_service,
            self._session_manager,
        )
        idempotency = await orchestrator.check_idempotency(
            command=command,
            trace_attrs=trace_attrs,
            span_name="chat.stream.idempotency_check",
        )
        if not idempotency.is_new:
            if idempotency.is_processing_duplicate:
                yield error_event("正在加速计算中...")
                yield done_event()
                return
            yield error_event("该请求已完成，请刷新页面")
            yield done_event()
            return

        # 会话和消息创建放在 DB 槽位内，避免高并发下耗尽连接池。
        try:
            prepared = await orchestrator.prepare_request(
                command=command,
                idempotency=idempotency,
                trace_attrs=trace_attrs,
                span_prefix="chat.stream",
            )
        except AppException as exc:
            yield error_event(str(exc))
            yield done_event()
            return
        session = prepared.session
        assistant_msg = prepared.assistant_message

        # 先发送 meta，让前端尽早拿到会话和消息 id。
        yield meta_event(
            session_id=str(session.id),
            session_title=session.title,
            message_id=str(assistant_msg.id),
        )

        task_id = str(uuid.uuid4())
        channel = f"stream:{task_id}"

        pubsub = None
        worker_wait_started: float | None = None
        queue_wait_ms: int | None = None
        # Web-observed first token: HTTP request received -> first SSE chunk yielded.
        e2e_first_token_ms: int | None = None
        try:
            with trace_span(
                "chat.stream.dispatch_task",
                {**prepared.trace_attrs, "task.id": task_id, "redis.channel": channel},
            ):
                # 必须先订阅后投递，避免 worker 首包发布过快导致丢消息。
                pubsub = self.redis.pubsub()
                await pubsub.subscribe(channel)
                worker_wait_started = perf_start()
                await self.dispatcher.enqueue_stream(
                    prepared.generation_payload.model_dump(mode="json"),
                    channel,
                    inject_trace_context(),
                    str(assistant_msg.id),
                    str(user_id),
                    prepared.lock_key,
                )
        except AppException as exc:
            await orchestrator.release_idempotency(idempotency)
            logger.warning("流式任务初始化失败: %s", exc)
            yield error_event(str(exc))
            async with db_concurrency_slot(prepared.trace_attrs), self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_failed(assistant_msg.id)
            yield done_event()
            return
        except Exception as exc:
            await orchestrator.release_idempotency(idempotency)
            logger.error("流式任务初始化异常: %s", str(exc), exc_info=True)
            yield error_event("服务暂时不可用，请稍后重试")
            async with db_concurrency_slot(prepared.trace_attrs), self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_failed(assistant_msg.id)
            yield done_event()
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
                {**prepared.trace_attrs, "task.id": task_id, "redis.channel": channel},
            ) as span:
                loop = asyncio.get_running_loop()
                deadline = (
                    loop.time() + settings.CHAT_STREAM_FIRST_MESSAGE_TIMEOUT_SECONDS
                )
                while loop.time() < deadline:
                    remaining = deadline - loop.time()
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
                    event = decode_stream_event(first_payload)
                    event_type = event.get("type")
                    if event_type == "started":
                        if worker_wait_started is not None and queue_wait_ms is None:
                            queue_wait_ms = elapsed_ms(worker_wait_started)
                        continue
                    if event_type == "done":
                        done_received = True
                    elif event_type == "error":
                        raise app_service_error(
                            f"Taskiq 队列执行 LLM 错误: {event.get('message', '')}",
                            code="LLM_TASK_FAILED",
                        )
                    else:
                        content = event.get("content", "")
                        e2e_first_token_ms = elapsed_ms(request_started)
                        accumulated_content.append(content)
                        yield chunk_event(content)
                    break
                else:
                    raise app_service_error(
                        "LLM 响应超时，请稍后重试", code="LLM_TIMEOUT"
                    )

                if not done_received:
                    while not done_received:
                        try:
                            message = await asyncio.wait_for(
                                anext(stream_iter),
                                timeout=settings.CHAT_STREAM_MESSAGE_TIMEOUT_SECONDS,
                            )
                        except TimeoutError as exc:
                            raise app_service_error(
                                "LLM 流式消息间超时，请稍后重试",
                                code="LLM_STREAM_MESSAGE_TIMEOUT",
                            ) from exc
                        except StopAsyncIteration:
                            break
                        payload = _read_stream_payload(message)
                        if payload is None:
                            continue
                        event = decode_stream_event(payload)
                        event_type = event.get("type")
                        if event_type == "started":
                            if (
                                worker_wait_started is not None
                                and queue_wait_ms is None
                            ):
                                queue_wait_ms = elapsed_ms(worker_wait_started)
                            continue
                        if event_type == "done":
                            done_received = True
                            break
                        if event_type == "error":
                            raise app_service_error(
                                f"Taskiq 队列执行 LLM 错误: {event.get('message', '')}",
                                code="LLM_TASK_FAILED",
                            )
                        content = event.get("content", "")
                        if e2e_first_token_ms is None:
                            e2e_first_token_ms = elapsed_ms(request_started)
                        accumulated_content.append(content)
                        yield chunk_event(content)

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
                        "chat.queue_wait_ms": queue_wait_ms,
                        "chat.e2e_first_token_ms": e2e_first_token_ms,
                    },
                )
                await self._merge_web_stream_metrics(
                    assistant_message_id=assistant_msg.id,
                    trace_attrs=prepared.trace_attrs,
                    metrics={
                        "queue_wait_ms": queue_wait_ms,
                        "e2e_first_token_ms": e2e_first_token_ms,
                    },
                )
        except AppException as exc:
            logger.warning("流式 LLM 调用业务异常: %s", exc)
            yield error_event(str(exc))
            yield done_event()
            return
        except Exception as exc:
            logger.error("流式 LLM 调用异常: %s", str(exc), exc_info=True)
            yield error_event("服务暂时不可用，请稍后重试")
            yield done_event()
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

        yield done_event()

    async def _merge_web_stream_metrics(
        self,
        *,
        assistant_message_id: uuid.UUID,
        trace_attrs: dict[str, object],
        metrics: dict[str, object | None],
    ) -> None:
        filtered = {key: value for key, value in metrics.items() if value is not None}
        if not filtered:
            return
        try:
            async with db_concurrency_slot(trace_attrs), self.uow:
                message = await self.uow.chat_repo.get_message(assistant_message_id)
                if message is None:
                    logger.warning(
                        "流式指标回写跳过，助手消息不存在: message_id=%s",
                        assistant_message_id,
                    )
                    return
                merged_metadata = merge_metrics(
                    getattr(message, "message_metadata", None),
                    filtered,
                )
                await self.uow.chat_repo.update_message_status(
                    message_id=assistant_message_id,
                    status=message.status,
                    message_metadata=merged_metadata,
                )
        except Exception:
            logger.debug(
                "流式指标回写失败: message_id=%s",
                assistant_message_id,
                exc_info=True,
            )
