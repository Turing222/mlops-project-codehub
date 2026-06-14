"""Non-streaming chat workflow.

职责：编排非流式聊天请求的幂等、会话消息和 Worker 任务投递。
边界：LLM 调用和最终消息持久化由 Worker 拥有；本模块只负责 Web 侧编排和 HTTP 响应。
失败处理：任务投递前失败由 Web 回写；任务投递后最终消息状态由 Worker 拥有。
"""

import logging

import redis.asyncio as redis

from backend.application.chat.session_orchestrator import ChatSessionOrchestrator
from backend.contracts.interfaces import (
    AbstractTaskDispatcher,
    AbstractUnitOfWork,
)
from backend.core.exceptions import (
    AppException,
    app_service_error,
)
from backend.models.enums import MessageStatus
from backend.models.schemas.chat.api import (
    ChatQueryResponse,
    MessageResponse,
)
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.observability.langfuse_utils import set_langfuse_trace_metadata
from backend.observability.trace_utils import (
    inject_trace_context,
    trace_span,
)
from backend.services.chat_service import SessionManager
from backend.services.feature_flag_service import FeatureFlagService
from backend.services.permission_service import PermissionService

logger = logging.getLogger(__name__)


class ChatNonStreamWorkflow:
    """非流式对话编排器 —— Web 侧负责会话管理、RAG 检索、Worker 投递。"""

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

    # ── Main handler ──────────────────────────────────────────────

    async def handle_query(
        self,
        command: ChatQueryCommand,
    ) -> ChatQueryResponse:
        with set_langfuse_trace_metadata(
            user_id=command.user_id,
            session_id=command.session_id,
            tags=["chat_api", "non-stream"],
        ):
            return await self._handle_query(command)

    async def _handle_query(
        self,
        command: ChatQueryCommand,
    ) -> ChatQueryResponse:
        user_id = command.user_id
        query_text = command.query_text
        session_id = command.session_id
        kb_id = command.kb_id
        client_request_id = command.client_request_id
        logger.info(
            "Workflow 收到查询: user_id=%s, session_id=%s, query_len=%d",
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
            "chat.stream": False,
        }

        # ── 幂等检查 ──────────────────────────────────────────────

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
            span_name="chat.nonstream.idempotency_check",
        )
        if not idempotency.is_new:
            if client_request_id is None:
                raise app_service_error(
                    "请求幂等状态异常",
                    code="CHAT_IDEMPOTENCY_STATE_INVALID",
                )
            if idempotency.is_processing_duplicate:
                raise app_service_error(
                    "正在加速计算中...",
                    code="CHAT_REQUEST_PROCESSING",
                    details={"client_request_id": client_request_id},
                )
            async with self.uow.read_context():
                msg = await self.uow.chat_repo.get_message_by_client_request_id(
                    client_request_id,
                    user_id,
                )
                if msg and msg.status == MessageStatus.SUCCESS:
                    session = await self.uow.chat_repo.get_session(msg.session_id)
                    if session is None:
                        raise app_service_error(
                            "会话不存在",
                            code="CHAT_SESSION_NOT_FOUND",
                        )
                    return ChatQueryResponse(
                        session_id=session.id,
                        session_title=session.title,
                        answer=MessageResponse.model_validate(msg),
                    )
                status_value = msg.status.value if msg and msg.status else "NOT_FOUND"
            raise app_service_error(
                "该请求正在处理或已结束，请刷新页面后重试",
                code="CHAT_REQUEST_PROCESSING",
                details={
                    "client_request_id": client_request_id,
                    "message_status": status_value,
                },
            )

        # ── 会话与消息创建 ────────────────────────────────────────

        prepared = await orchestrator.prepare_request(
            command=command,
            idempotency=idempotency,
            trace_attrs=trace_attrs,
            span_prefix="chat.nonstream",
        )
        session = prepared.session
        assistant_msg = prepared.assistant_message

        try:
            with trace_span(
                "chat.nonstream.dispatch_task",
                {
                    **prepared.trace_attrs,
                    "chat.assistant_message_id": assistant_msg.id,
                },
            ):
                result = await self.dispatcher.enqueue_nonstream(
                    prepared.generation_payload.model_dump(mode="json"),
                    inject_trace_context(),
                    str(assistant_msg.id),
                    str(user_id),
                    prepared.lock_key,
                )
        except AppException:
            await orchestrator.release_idempotency(idempotency)
            raise
        except Exception as exc:
            await orchestrator.release_idempotency(idempotency)
            raise app_service_error(
                "LLM 服务调用失败，请稍后重试",
                code="LLM_SERVICE_ERROR",
            ) from exc

        if not result or not result.success:
            error_msg = result.error if result and result.error else "LLM 服务返回失败"
            raise app_service_error(
                error_msg,
                code="LLM_SERVICE_FAILED",
                details={"error": error_msg},
            )

        # Worker 已持久化成功消息并更新幂等锁；Web 直接构造响应。
        answer = MessageResponse(
            id=assistant_msg.id,
            session_id=session.id,
            role="assistant",
            content=result.content,
            status=MessageStatus.SUCCESS,
            latency_ms=result.latency_ms,
            search_context=result.search_context,
            created_at=assistant_msg.created_at,
            updated_at=assistant_msg.updated_at,
        )

        return ChatQueryResponse(
            session_id=session.id,
            session_title=session.title,
            answer=answer,
        )
