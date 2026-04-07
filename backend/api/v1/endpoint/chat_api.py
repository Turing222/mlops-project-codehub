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
    get_chat_nonstream_workflow,
    get_chat_workflow,
    get_current_active_user,
    get_session_query_service,
)
from backend.middleware.rate_limit import RateLimiter
from backend.models.orm.user import User
from backend.models.schemas.chat_schema import (
    ChatQueryResponse,
    QuerySentRequest,
    SessionDetailResponse,
    SessionListResponse,
)
from backend.services.session_query_service import SessionQueryService
from backend.workflow.chat_nonstream_workflow import ChatNonStreamWorkflow
from backend.workflow.chat_workflow import ChatWorkflow

# 定义限流策略：为压测临时调高上限（原：每 60 秒 10 次）
chat_limiter = RateLimiter(times=100000, seconds=60)

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
) -> ChatQueryResponse:
    """
    用户发送查询（非流式）。
    """
    return await workflow.handle_query(
        user_id=current_user.id,
        query_text=request.query,
        session_id=request.session_id,
        kb_id=request.kb_id,
        client_request_id=request.client_request_id,
    )


@router.post("/query_stream")
async def query_stream(
    request: QuerySentRequest,
    current_user: CurrentUser,
    workflow: StreamWorkflowDep,
    _: ChatRateLimitDep,
) -> StreamingResponse:
    """
    用户发送查询（SSE 流式响应）。

    事件格式:
    - data: {"type":"meta","session_id":"...","session_title":"...","message_id":"..."}
    - data: {"type":"chunk","content":"..."}
    - data: {"type":"error","message":"..."}
    - data: [DONE]
    """
    return StreamingResponse(
        workflow.handle_query_stream(
            user_id=current_user.id,
            query_text=request.query,
            session_id=request.session_id,
            kb_id=request.kb_id,
            client_request_id=request.client_request_id,
        ),
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
) -> SessionDetailResponse:
    """获取会话详情及历史消息"""
    async with session_query_service.uow:
        return await session_query_service.get_user_session_detail(
            user_id=current_user.id,
            session_id=session_id,
            skip=skip,
            limit=limit,
        )
