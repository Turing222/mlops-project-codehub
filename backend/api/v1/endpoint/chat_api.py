"""
Chat API — 对话相关的 HTTP 端点

企业级设计：
- 使用 Pydantic Schema 做输入校验与输出序列化
- 统一异常处理（通过项目异常类自动映射 HTTP 状态码）
- 结构化日志记录请求生命周期
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import (
    get_chat_workflow,
    get_current_active_user,
    get_uow,
)
from backend.models.orm.user import User
from backend.models.schemas.chat_schema import (
    ChatQueryResponse,
    MessageResponse,
    QuerySentRequest,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
)
from backend.services.chat_service import SessionManager
from backend.services.unit_of_work import AbstractUnitOfWork
from backend.workflow.chat_workflow import ChatWorkflow

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/query_sent", response_model=ChatQueryResponse)
async def query_sent(
    request: QuerySentRequest,
    current_user: User = Depends(get_current_active_user),
    workflow: ChatWorkflow = Depends(get_chat_workflow),
):
    """
    用户发送查询。
    """
    return await workflow.handle_query(
        user_id=current_user.id,
        query_text=request.query,
        session_id=request.session_id,
        kb_id=request.kb_id,
    )


@router.get("/sessions", response_model=SessionListResponse)
async def get_sessions(
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(default=20, ge=1, le=100, description="每页记录数"),
    current_user: User = Depends(get_current_active_user),
    uow: AbstractUnitOfWork = Depends(get_uow),
):
    """获取当前用户的会话列表（侧边栏）"""
    logger.debug(
        "获取会话列表: user_id=%s, skip=%d, limit=%d", current_user.id, skip, limit
    )

    async with uow:
        session_manager = SessionManager(uow)
        sessions = await session_manager.get_user_sessions(
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )

    return SessionListResponse(
        items=[SessionResponse.model_validate(s) for s in sessions],
        total=len(sessions),
        skip=skip,
        limit=limit,
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_active_user),
    uow: AbstractUnitOfWork = Depends(get_uow),
):
    """获取会话详情及历史消息"""
    logger.debug("获取会话详情: session_id=%s, user_id=%s", session_id, current_user.id)

    async with uow:
        session_manager = SessionManager(uow)
        # ensure_session 会验证权限
        session = await session_manager.ensure_session(
            user_id=current_user.id,
            query_text="",
            session_id=session_id,
        )
        messages = await session_manager.get_session_messages(
            session_id=session.id,
            skip=skip,
            limit=limit,
        )

    return SessionDetailResponse(
        session=SessionResponse.model_validate(session),
        messages=[MessageResponse.model_validate(m) for m in messages],
        total_messages=len(messages),
    )
