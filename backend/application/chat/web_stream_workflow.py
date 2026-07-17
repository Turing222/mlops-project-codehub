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

from backend.application.chat.session_orchestrator import (
    ChatPreparedRequest,
    ChatSessionOrchestrator,
)
from backend.application.chat.stream_events import (
    SSEEvent,
    StreamEvent,
    chunk_event,
    decode_stream_event,
    done_event,
    error_event,
    meta_event,
    step_event,
)
from backend.application.chat.timing import elapsed_ms, merge_metrics, perf_start
from backend.config.settings import settings
from backend.contracts.interfaces import (
    AbstractTaskDispatcher,
    AbstractUnitOfWork,
)
from backend.core.concurrency import db_concurrency_slot
from backend.core.exceptions import AppException, app_not_found, app_service_error
from backend.infra.redis import safe_release_lock
from backend.models.enums import ChatGenerationDispatchMode
from backend.models.orm.chat import ChatGenerationRequest
from backend.models.orm.user import User
from backend.models.schemas.chat.api import GenerationRequestStatusResponse
from backend.models.schemas.chat.commands import (
    ChatQueryCommand,
    RetryChatGenerationCommand,
)
from backend.observability.langfuse_utils import set_langfuse_trace_metadata
from backend.observability.trace_utils import (
    inject_trace_context,
    set_span_attributes,
    trace_span,
)
from backend.services.chat_service import SessionManager
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

    async def get_generation_request_status(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> GenerationRequestStatusResponse:
        """Resolve one durable generation request for its current actor."""
        async with self.uow.read_context():
            generation_request = (
                await self.uow.chat_repo.get_generation_request_for_actor(
                    request_id=request_id,
                    user_id=user_id,
                )
            )
        if generation_request is None:
            raise app_not_found(
                "生成请求不存在",
                code="CHAT_GENERATION_REQUEST_NOT_FOUND",
                details={"generation_request_id": str(request_id)},
            )
        return self._to_status_response(generation_request)

    async def resolve_generation_request_status(
        self,
        *,
        client_request_id: str,
        user_id: uuid.UUID,
    ) -> GenerationRequestStatusResponse:
        """Resolve accepted identity after an ambiguous transport failure."""
        async with self.uow.read_context():
            generation_request = await self.uow.chat_repo.get_generation_request_by_client_request_id_for_actor(
                user_id=user_id,
                client_request_id=client_request_id,
            )
        if generation_request is None:
            raise app_not_found(
                "生成请求不存在",
                code="CHAT_GENERATION_REQUEST_NOT_FOUND",
                details={"client_request_id": client_request_id},
            )
        return self._to_status_response(generation_request)

    async def handle_retry_stream(
        self,
        *,
        command: RetryChatGenerationCommand,
        user: User,
    ) -> AsyncGenerator[SSEEvent, None]:
        """Retry one authorized terminal failure and stream its next attempt."""
        user_features = await self._feature_flag_service.get_user_features(user)
        if not user_features.get("chat-explicit-retry", False):
            yield error_event(
                "显式重试功能尚未启用",
                error_code="CHAT_EXPLICIT_RETRY_DISABLED",
                retryable=False,
                generation_request_id=str(command.generation_request_id),
                attempt=command.expected_attempt,
            )
            yield done_event()
            return

        trace_attrs: dict[str, object] = {
            "chat.user_id": command.user_id,
            "chat.generation_request_id": command.generation_request_id,
            "chat.generation_attempt.expected": command.expected_attempt,
            "chat.stream": True,
            "chat.retry": True,
        }
        orchestrator = ChatSessionOrchestrator(
            self.uow,
            self.redis,
            self.permission_service,
            self._feature_flag_service,
            self._session_manager,
        )
        try:
            prepared = await orchestrator.prepare_retry_request(
                command=command,
                trace_attrs=trace_attrs,
            )
        except AppException as exc:
            yield error_event(
                str(exc),
                error_code=exc.code,
                retryable=False,
                generation_request_id=str(command.generation_request_id),
                attempt=command.expected_attempt,
            )
            yield done_event()
            return

        retry_query = ChatQueryCommand(
            user_id=command.user_id,
            query_text=prepared.generation_payload.query_text,
            session_id=prepared.session.id,
            kb_id=prepared.generation_payload.kb_id,
            enable_external_context=(
                prepared.generation_payload.enable_external_context
            ),
            context_mode=prepared.generation_payload.context_mode,
            extra_body=prepared.generation_payload.extra_body,
        )
        with set_langfuse_trace_metadata(
            user_id=command.user_id,
            session_id=prepared.session.id,
            tags=["chat_api", "stream", "explicit_retry"],
        ):
            async for event in self._handle_query_stream(
                retry_query,
                prepared_request=prepared,
            ):
                yield event

    @staticmethod
    def _to_status_response(
        generation_request: ChatGenerationRequest,
    ) -> GenerationRequestStatusResponse:
        return GenerationRequestStatusResponse(
            generation_request_id=generation_request.id,
            client_request_id=generation_request.client_request_id,
            session_id=generation_request.session_id,
            assistant_message_id=generation_request.assistant_message_id,
            status=generation_request.status,
            attempt=generation_request.attempt,
            retryable=generation_request.retryable,
            error_code=generation_request.error_code,
            error_message=generation_request.error_message,
            created_at=generation_request.created_at,
            updated_at=generation_request.updated_at,
            finished_at=generation_request.finished_at,
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
        *,
        prepared_request: ChatPreparedRequest | None = None,
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

        trace_attrs = dict(prepared_request.trace_attrs) if prepared_request else {}
        trace_attrs.update(
            {
                "chat.user_id": user_id,
                "chat.session_id": session_id,
                "chat.kb_id": kb_id,
                "chat.client_request_id.present": client_request_id is not None,
                "chat.query.char_count": len(query_text),
                "chat.stream": True,
            }
        )

        # 幂等锁避免同一 client_request_id 并发生成多条助手消息。
        orchestrator = ChatSessionOrchestrator(
            self.uow,
            self.redis,
            self.permission_service,
            self._feature_flag_service,
            self._session_manager,
        )
        if prepared_request is None:
            existing_request = await orchestrator.resolve_existing_generation_request(
                command=command
            )
            if existing_request is not None:
                yield error_event(
                    "该请求已被接受，请刷新页面查看状态",
                    error_code="CHAT_REQUEST_ALREADY_EXISTS",
                    retryable=False,
                    generation_request_id=str(existing_request.id),
                    attempt=existing_request.attempt,
                )
                yield done_event()
                return
            idempotency = await orchestrator.check_idempotency(
                command=command,
                trace_attrs=trace_attrs,
                span_name="chat.stream.idempotency_check",
            )
            if not idempotency.is_new:
                error_code = (
                    "CHAT_REQUEST_PROCESSING"
                    if idempotency.is_processing_duplicate
                    else "CHAT_REQUEST_ALREADY_EXISTS"
                )
                yield error_event(
                    "请求正在处理中，请刷新页面查看状态",
                    error_code=error_code,
                    retryable=False,
                )
                yield done_event()
                return

            try:
                prepared = await orchestrator.prepare_request(
                    command=command,
                    idempotency=idempotency,
                    trace_attrs=trace_attrs,
                    span_prefix="chat.stream",
                    dispatch_mode=ChatGenerationDispatchMode.STREAM,
                )
            except AppException as exc:
                yield error_event(
                    str(exc),
                    error_code=exc.code,
                    retryable=False,
                )
                yield done_event()
                return
        else:
            prepared = prepared_request
        session = prepared.session
        assistant_msg = prepared.assistant_message

        task_id = uuid.uuid4().hex
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
                generation_attempt = await orchestrator.queue_generation_request(
                    prepared=prepared,
                    user_id=user_id,
                    task_id=task_id,
                )
                await self.dispatcher.enqueue_stream(
                    generation_payload=prepared.generation_payload.model_dump(
                        mode="json"
                    ),
                    channel=channel,
                    trace_context=inject_trace_context(),
                    assistant_message_id=str(assistant_msg.id),
                    user_id=str(user_id),
                    idempotency_lock_key=prepared.lock_key,
                    generation_attempt=generation_attempt,
                )
        except AppException as exc:
            await self._release_prepared_lock(prepared)
            await self._close_pubsub(pubsub, channel)
            pubsub = None
            logger.warning("流式任务初始化失败: %s", exc)
            yield error_event(
                str(exc),
                error_code=exc.code,
                retryable=False,
                generation_request_id=str(prepared.generation_request.id),
                attempt=prepared.generation_request.attempt,
            )
            yield done_event()
            return
        except Exception as exc:
            await self._release_prepared_lock(prepared)
            await self._close_pubsub(pubsub, channel)
            pubsub = None
            logger.error("流式任务初始化异常: %s", str(exc), exc_info=True)
            yield error_event(
                "请求已接受，正在恢复派发，请稍后刷新",
                error_code="CHAT_DISPATCH_RECOVERY_PENDING",
                retryable=False,
                generation_request_id=str(prepared.generation_request.id),
                attempt=prepared.generation_request.attempt,
            )
            yield done_event()
            return

        # Only expose message identity after the durable request is queued and
        # broker dispatch has returned, so disconnecting after meta cannot skip dispatch.
        yield meta_event(
            session_id=str(session.id),
            session_title=session.title,
            message_id=str(assistant_msg.id),
            generation_request_id=str(prepared.generation_request.id),
            attempt=prepared.generation_request.attempt,
        )

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

        def _yield_worker_event(event: StreamEvent) -> SSEEvent | None:
            event_type = event.get("type")
            if event_type == "step":
                return step_event(
                    step=str(event.get("step") or ""),
                    status=event.get("status") or "running",
                    metrics=event.get("metrics"),
                )
            if event_type == "chunk":
                return chunk_event(str(event.get("content") or ""))
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
                        raise AppException(
                            code=str(event.get("error_code") or "LLM_TASK_FAILED"),
                            message=str(event.get("message") or "LLM 服务错误"),
                            status_code=500,
                            details={"retryable": event.get("retryable") is True},
                        )
                    elif event_type == "step":
                        sse_step = _yield_worker_event(event)
                        if sse_step is not None:
                            yield sse_step
                        continue
                    elif event_type == "chunk":
                        content = event.get("content", "")
                        e2e_first_token_ms = elapsed_ms(request_started)
                        accumulated_content.append(content)
                        yield chunk_event(content)
                        break
                    else:
                        content = event.get("content", "")
                        if content:
                            e2e_first_token_ms = elapsed_ms(request_started)
                            accumulated_content.append(content)
                            yield chunk_event(content)
                            break
                        continue
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
                            raise AppException(
                                code=str(event.get("error_code") or "LLM_TASK_FAILED"),
                                message=str(event.get("message") or "LLM 服务错误"),
                                status_code=500,
                                details={"retryable": event.get("retryable") is True},
                            )
                        if event_type == "step":
                            sse_step = _yield_worker_event(event)
                            if sse_step is not None:
                                yield sse_step
                            continue
                        if event_type == "chunk":
                            content = event.get("content", "")
                            if e2e_first_token_ms is None:
                                e2e_first_token_ms = elapsed_ms(request_started)
                            accumulated_content.append(content)
                            yield chunk_event(content)
                            continue
                        content = event.get("content", "")
                        if content:
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
            yield error_event(
                str(exc),
                error_code=exc.code,
                retryable=exc.details.get("retryable") is True,
                generation_request_id=str(prepared.generation_request.id),
                attempt=prepared.generation_request.attempt,
            )
            yield done_event()
            return
        except Exception as exc:
            logger.error("流式 LLM 调用异常: %s", str(exc), exc_info=True)
            yield error_event(
                "服务暂时不可用，请稍后重试",
                error_code="CHAT_STREAM_FAILED",
                retryable=False,
                generation_request_id=str(prepared.generation_request.id),
                attempt=prepared.generation_request.attempt,
            )
            yield done_event()
            return
        finally:
            await self._close_pubsub(pubsub, channel)

        yield done_event()

    async def _release_prepared_lock(self, prepared: ChatPreparedRequest) -> None:
        if prepared.lock_key is None or prepared.lock_token is None:
            return
        await safe_release_lock(
            self.redis,
            prepared.lock_key,
            prepared.lock_token,
        )

    @staticmethod
    async def _close_pubsub(pubsub: object | None, channel: str) -> None:
        if pubsub is None:
            return
        try:
            unsubscribe = getattr(pubsub, "unsubscribe", None)
            if unsubscribe is not None:
                maybe_awaitable = unsubscribe(channel)
                if asyncio.iscoroutine(maybe_awaitable):
                    await maybe_awaitable
        except Exception:
            logger.debug("Redis 取消订阅失败: channel=%s", channel, exc_info=True)
        try:
            close_fn = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if close_fn is not None:
                maybe_awaitable = close_fn()
                if asyncio.iscoroutine(maybe_awaitable):
                    await maybe_awaitable
        except Exception:
            logger.debug("Redis PubSub 关闭失败: channel=%s", channel, exc_info=True)

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
