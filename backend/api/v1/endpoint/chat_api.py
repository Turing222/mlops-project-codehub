"""
Chat API — 对话相关的 HTTP 端点

企业级设计：
- 使用 Pydantic Schema 做输入校验与输出序列化
- 统一异常处理（通过项目异常类自动映射 HTTP 状态码）
- 结构化日志记录请求生命周期
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from backend.api.dependencies import (
    get_audit_service,
    get_chat_nonstream_workflow,
    get_chat_workflow,
    get_current_active_user,
    get_permission_service,
    get_session_query_service,
)
from backend.core.config import settings
from backend.middleware.rate_limit import RateLimiter
from backend.models.orm.user import User
from backend.models.schemas.chat_schema import (
    ChatQueryResponse,
    QuerySentRequest,
    SessionDetailResponse,
    SessionListResponse,
)
from backend.services.audit_service import AuditAction, AuditService, capture_audit
from backend.services.permission_service import PermissionService
from backend.services.session_query_service import SessionQueryService
from backend.workflow.chat_nonstream_workflow import ChatNonStreamWorkflow
from backend.workflow.chat_workflow import ChatWorkflow

# R8 修复：限流参数从 settings 读取，通过环境变量控制（CHAT_RATE_LIMIT_TIMES / CHAT_RATE_LIMIT_SECONDS）
# 压测时可设 CHAT_RATE_LIMIT_TIMES=100000，生产环境保持安全默认值（10次/60秒）
chat_limiter = RateLimiter(
    times=settings.CHAT_RATE_LIMIT_TIMES,
    seconds=settings.CHAT_RATE_LIMIT_SECONDS,
)

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
SessionQueryServiceDep = Annotated[
    SessionQueryService, Depends(get_session_query_service)
]
NonStreamWorkflowDep = Annotated[
    ChatNonStreamWorkflow, Depends(get_chat_nonstream_workflow)
]
StreamWorkflowDep = Annotated[ChatWorkflow, Depends(get_chat_workflow)]
ChatRateLimitDep = Annotated[None, Depends(chat_limiter)]
SessionSkipParam = Annotated[int, Query(ge=0, description="跳过的记录数")]
SessionListLimitParam = Annotated[int, Query(ge=1, le=100, description="每页记录数")]
SessionDetailLimitParam = Annotated[int, Query(ge=1, le=500)]


@router.post("/query_sent", response_model=ChatQueryResponse)
async def query_sent(
    request: QuerySentRequest,
    current_user: CurrentUser,
    workflow: NonStreamWorkflowDep,
    _: ChatRateLimitDep,
    permission_service: PermissionService = Depends(get_permission_service),
    audit_service: AuditService = Depends(get_audit_service),
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
        },
    ) as audit:
        result = await workflow.handle_query(
            user_id=current_user.id,
            query_text=request.query,
            session_id=request.session_id,
            kb_id=request.kb_id,
            client_request_id=request.client_request_id,
        )
        audit.set_resource(resource_id=result.answer.id)
        audit.add_metadata(session_id=str(result.session_id))
        return result


@router.post("/query_stream")
async def query_stream(
    request: QuerySentRequest,
    current_user: CurrentUser,
    workflow: StreamWorkflowDep,
    _: ChatRateLimitDep,
    permission_service: PermissionService = Depends(get_permission_service),
    audit_service: AuditService = Depends(get_audit_service),
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
    import json as _json

    async def _audited_stream():
        async with capture_audit(
            audit_service,
            action=AuditAction.CHAT_QUERY_STREAM,
            actor_user_id=current_user.id,
            resource_type="chat_session",
            resource_id=request.session_id,  # 新会话时为 None，meta 事件后更新
            metadata={
                "kb_id": str(request.kb_id) if request.kb_id else None,
                "client_request_id": request.client_request_id,
            },
        ) as audit:
            meta_captured = False
            async for chunk in workflow.handle_query_stream(
                user_id=current_user.id,
                query_text=request.query,
                session_id=request.session_id,
                kb_id=request.kb_id,
                client_request_id=request.client_request_id,
            ):
                # 仅在首个 meta 事件时更新 audit resource_id（session_id / message_id）
                if not meta_captured and isinstance(chunk, str) and chunk.startswith("data:"):
                    payload_str = chunk.removeprefix("data:").strip()
                    if payload_str and payload_str != "[DONE]":
                        try:
                            payload = _json.loads(payload_str)
                            if payload.get("type") == "meta":
                                meta_captured = True
                                _sid = payload.get("session_id")
                                _mid = payload.get("message_id")
                                try:
                                    audit.set_resource(
                                        resource_id=uuid.UUID(_mid) if _mid else (
                                            uuid.UUID(_sid) if _sid else None
                                        )
                                    )
                                    audit.add_metadata(session_id=_sid)
                                except (ValueError, AttributeError):
                                    pass
                        except _json.JSONDecodeError:
                            pass
                yield chunk
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


@router.get("/sessions", response_model=SessionListResponse)
async def get_sessions(
    current_user: CurrentUser,
    session_query_service: SessionQueryServiceDep,
    skip: SessionSkipParam = 0,
    limit: SessionListLimitParam = 20,
    permission_service: PermissionService = Depends(get_permission_service),
) -> SessionListResponse:
    """获取当前用户的会话列表（侧边栏）"""
    async with session_query_service.uow:
        return await session_query_service.list_user_sessions(
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    session_query_service: SessionQueryServiceDep,
    skip: SessionSkipParam = 0,
    limit: SessionDetailLimitParam = 100,
    permission_service: PermissionService = Depends(get_permission_service),
) -> SessionDetailResponse:
    """获取会话详情及历史消息"""
    async with session_query_service.uow:
        return await session_query_service.get_user_session_detail(
            user_id=current_user.id,
            session_id=session_id,
            skip=skip,
            limit=limit,
        )
