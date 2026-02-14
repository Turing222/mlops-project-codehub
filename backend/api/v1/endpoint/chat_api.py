import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from backend.api.dependencies import get_current_active_user, get_uow
from backend.models.orm.user import User


from backend.models.schemas.chat_schema import ChatBase
from backend.services.chat_service import SessionManager, ChatMessageUpdater
from backend.services.llm_service import LLMService
from backend.services.unit_of_work import AbstractUnitOfWork


router = APIRouter()


# 增加任务管理上下文
# 增加redis缓存上下文
@router.post("/query_sent", response_model=ChatBase)
async def query_sent(
    current_user: User = Depends(get_current_active_user),
    uow: AbstractUnitOfWork = Depends(get_uow),
    Query: str | None = None,
    session_id: str = None,
):
    # 创建session 或者查询session
    async with uow:
        session_manager = SessionManager(uow)
        session = await session_manager.ensure_session(
            user_id=current_user.id,
            query_text=Query or "",
            session_id=uuid.UUID(session_id) if session_id else None,
        )
    # 调用llm模型返回结果

    try:
        content = await run_in_threadpool(
            LLMService.process_query, session.id, Query or ""
        )
    except Exception as e:
        async with uow:
            chat_message_updater = ChatMessageUpdater(uow)
            await chat_message_updater.update_as_failed(session.id, "failed")
        raise HTTPException(status_code=500, detail="处理查询时出错") from e
    # 更新消息状态为 done
    async with uow:
        chat_message_updater = ChatMessageUpdater(uow)
        await chat_message_updater.update_message_status(session.id, "done")
        await session_manager.create_user_message(
            session_id=session.id, content=content
        )

    return "done"


@router.get("/side", response_model=ChatBase)
async def get_side(
    current_user: User = Depends(get_current_active_user),
    uow: AbstractUnitOfWork = Depends(get_uow),
):
    # 返回侧边栏信息
    return list(biaoti for biaoti in ["对话记录schema"])


@router.get("/chat_session", response_model=ChatBase)
async def get_chat_session(
    current_user: User = Depends(get_current_active_user),
    uow: AbstractUnitOfWork = Depends(get_uow),
):
    # 用于查询历史记录

    return "对话记录schema"
