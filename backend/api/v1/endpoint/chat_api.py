"""
Chat API — 对话相关的 HTTP 端点

企业级设计：
- 使用 Pydantic Schema 做输入校验与输出序列化
- 统一异常处理（通过项目异常类自动映射 HTTP 状态码）
- 结构化日志记录请求生命周期
"""

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from backend.api.dependencies import (
    get_audit_service,
    get_chat_nonstream_workflow,
    get_chat_workflow,
    get_current_active_user,
    get_session_query_service,
)
from backend.api.v1.sse_events import encode_sse_event
from backend.application.chat.web_nonstream_workflow import ChatNonStreamWorkflow
from backend.application.chat.web_stream_workflow import ChatWorkflow
from backend.config.settings import settings
from backend.core.constants import (
    DEFAULT_PAGE_LIMIT,
    MAX_CHAT_MESSAGE_LIMIT,
    MAX_PAGE_LIMIT,
)
from backend.middleware.rate_limit import RateLimiter
from backend.models.orm.user import User
from backend.models.schemas.chat.api import (
    ChatQueryResponse,
    QuerySentRequest,
    SessionDetailResponse,
    SessionListResponse,
)
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.services.audit_service import AuditAction, AuditService, capture_audit
from backend.services.session_query_service import SessionQueryService

# R8 修复：限流参数从 settings 读取，通过环境变量控制（CHAT_RATE_LIMIT_TIMES / CHAT_RATE_LIMIT_SECONDS）
# 压测时可设 CHAT_RATE_LIMIT_TIMES=100000，生产环境保持安全默认值（10次/60秒）
chat_limiter = RateLimiter(
    times=settings.CHAT_RATE_LIMIT_TIMES,
    seconds=settings.CHAT_RATE_LIMIT_SECONDS,
)

router = APIRouter()

logger = logging.getLogger(__name__)

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
SessionQueryServiceDep = Annotated[
    SessionQueryService, Depends(get_session_query_service)
]
NonStreamWorkflowDep = Annotated[
    ChatNonStreamWorkflow, Depends(get_chat_nonstream_workflow)
]
StreamWorkflowDep = Annotated[ChatWorkflow, Depends(get_chat_workflow)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


@router.post("/query_sent")
async def query_sent(
    request: QuerySentRequest,
    current_user: CurrentUserDep,
    workflow: NonStreamWorkflowDep,
    _: Annotated[None, Depends(chat_limiter)],
    audit_service: AuditServiceDep,
) -> ChatQueryResponse:
    """
    用户发送查询（非流式）。
    """
    async with capture_audit(
        audit_service,
        action=AuditAction.CHAT_QUERY_SENT,
        actor_user_id=current_user.id,
        resource_type="chat_message",
        metadata={
            "session_id": str(request.session_id) if request.session_id else None,
            "kb_id": str(request.kb_id) if request.kb_id else None,
            "client_request_id": request.client_request_id,
            "enable_external_context": request.enable_external_context,
            "context_mode": request.context_mode,
        },
    ) as audit:
        extra_body = (
            request.extra_body.to_provider_dict() if request.extra_body else None
        )
        command = ChatQueryCommand(
            user_id=current_user.id,
            query_text=request.query,
            session_id=request.session_id,
            kb_id=request.kb_id,
            client_request_id=request.client_request_id,
            enable_external_context=request.enable_external_context,
            context_mode=request.context_mode,
            extra_body=extra_body,
        )
        result = await workflow.handle_query(command)
        audit.set_resource(resource_id=result.answer.id)
        audit.add_metadata(session_id=str(result.session_id))
        return result


@router.post("/query_stream")
async def query_stream(
    http_request: Request,
    request: QuerySentRequest,
    current_user: CurrentUserDep,
    workflow: StreamWorkflowDep,
    _: Annotated[None, Depends(chat_limiter)],
    audit_service: AuditServiceDep,
) -> StreamingResponse:
    """
    用户发送查询（SSE 流式响应）。

    事件格式:
    - data: {"type":"meta","session_id":"...","session_title":"...","message_id":"..."}
    - data: {"type":"chunk","content":"..."}
    - data: {"type":"error","message":"..."}
    - data: [DONE]

    audit 生命周期绑定到 generator 内部，确保 LLM 全流程执行完毕
    （或中途异常）后才收口审计记录，避免在 StreamingResponse 返回
    时提前标记 success。meta 事件解析后同步更新 resource_id。
    """

    async def _audited_stream() -> AsyncIterator[str]:
        async with capture_audit(
            audit_service,
            action=AuditAction.CHAT_QUERY_STREAM,
            actor_user_id=current_user.id,
            resource_type="chat_session",
            resource_id=request.session_id,  # 新会话时为 None，meta 事件后更新
            metadata={
                "kb_id": str(request.kb_id) if request.kb_id else None,
                "client_request_id": request.client_request_id,
                "enable_external_context": request.enable_external_context,
                "context_mode": request.context_mode,
            },
        ) as audit:
            extra_body = (
                request.extra_body.to_provider_dict() if request.extra_body else None
            )
            meta_captured = False
            command = ChatQueryCommand(
                user_id=current_user.id,
                query_text=request.query,
                session_id=request.session_id,
                kb_id=request.kb_id,
                client_request_id=request.client_request_id,
                enable_external_context=request.enable_external_context,
                context_mode=request.context_mode,
                extra_body=extra_body,
            )
            async for event in workflow.handle_query_stream(command):
                if await http_request.is_disconnected():
                    logger.warning(
                        "SSE 客户端已断开，提前终止流: user_id=%s, session_id=%s",
                        current_user.id,
                        request.session_id,
                    )
                    return
                # 仅在首个 meta 事件时更新 audit resource_id（session_id / message_id）
                if not meta_captured and event["type"] == "meta":
                    meta_captured = True
                    session_id = event.get("session_id")
                    message_id = event.get("message_id")
                    try:
                        audit.set_resource(
                            resource_id=uuid.UUID(message_id)
                            if message_id
                            else (uuid.UUID(session_id) if session_id else None)
                        )
                        audit.add_metadata(session_id=session_id)
                    except (ValueError, AttributeError):
                        pass
                yield encode_sse_event(event)
            # generator 正常结束 → capture_audit context 退出 → 标记 success

    return StreamingResponse(
        _audited_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions")
async def get_sessions(
    current_user: CurrentUserDep,
    session_query_service: SessionQueryServiceDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
) -> SessionListResponse:
    """获取当前用户的会话列表（侧边栏）"""
    async with session_query_service.read():
        return await session_query_service.list_user_sessions(
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: uuid.UUID,
    current_user: CurrentUserDep,
    session_query_service: SessionQueryServiceDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_CHAT_MESSAGE_LIMIT)] = MAX_PAGE_LIMIT,
) -> SessionDetailResponse:
    """获取会话详情及历史消息"""
    async with session_query_service.read():
        return await session_query_service.get_user_session_detail(
            user_id=current_user.id,
            session_id=session_id,
            skip=skip,
            limit=limit,
        )
