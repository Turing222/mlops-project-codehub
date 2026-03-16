import logging
import uuid

from backend.core.exceptions import ResourceNotFound, ValidationError
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.schemas.chat_schema import (
    MessageResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
)
from backend.services.base import BaseService

logger = logging.getLogger(__name__)


class SessionQueryService(BaseService[AbstractUnitOfWork]):
    """会话查询服务：封装会话列表与会话详情查询。"""

    async def list_user_sessions(
        self,
        *,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> SessionListResponse:
        logger.debug("获取会话列表: user_id=%s, skip=%d, limit=%d", user_id, skip, limit)

        rows = await self.uow.chat_repo.get_user_sessions_with_total_tokens(
            user_id=user_id,
            skip=skip,
            limit=limit,
        )
        total = await self.uow.chat_repo.count_user_sessions(user_id)

        items = [self._to_session_response(session, total_tokens) for session, total_tokens in rows]
        return SessionListResponse(
            items=items,
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get_user_session_detail(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> SessionDetailResponse:
        logger.debug("获取会话详情: session_id=%s, user_id=%s", session_id, user_id)

        session = await self.uow.chat_repo.get_session(session_id)
        if not session:
            raise ResourceNotFound(
                f"会话不存在: {session_id}",
                details={"session_id": str(session_id)},
            )
        if session.user_id != user_id:
            raise ValidationError(
                "无权访问该会话",
                details={"session_id": str(session_id)},
            )

        messages = await self.uow.chat_repo.get_session_messages(
            session_id=session.id,
            skip=skip,
            limit=limit,
        )
        total_messages = await self.uow.chat_repo.count_session_messages(session.id)
        total_tokens = await self.uow.chat_repo.get_session_total_tokens(session.id)

        session_res = self._to_session_response(session, total_tokens)
        return SessionDetailResponse(
            session=session_res,
            messages=[MessageResponse.model_validate(msg) for msg in messages],
            total_messages=total_messages,
        )

    @staticmethod
    def _to_session_response(session, total_tokens: int) -> SessionResponse:
        response = SessionResponse.model_validate(session)
        response.total_tokens = total_tokens
        return response
