"""Chat services.

职责：管理会话归属、消息创建和助手消息状态更新。
边界：本模块不调用 LLM、不组装 Prompt；对话编排由 workflow 负责。
风险：workspace 知识库必须重新校验成员权限，避免 owner 身份绕过降级后的权限。
"""

import logging
import time
import uuid

from backend.core.exceptions import app_forbidden, app_not_found
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.chat import ChatMessage, ChatSession, MessageStatus
from backend.services.base import BaseService
from backend.services.permission_service import Permission, PermissionService

logger = logging.getLogger(__name__)


class SessionManager(BaseService[AbstractUnitOfWork]):
    """负责会话确认、权限校验和消息创建。"""

    def __init__(self, uow: AbstractUnitOfWork) -> None:
        super().__init__(uow)

    async def ensure_session(
        self,
        user_id: uuid.UUID,
        query_text: str,
        session_id: uuid.UUID | None = None,
        kb_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
    ) -> ChatSession:
        """复用已有会话或创建新会话，并校验访问权限。"""
        if session_id:
            session = await self.uow.chat_repo.get_session(session_id)
            if not session:
                logger.warning(
                    "会话不存在: session_id=%s, user_id=%s", session_id, user_id
                )
                raise app_not_found(
                    f"会话不存在: {session_id}",
                    code="CHAT_SESSION_NOT_FOUND",
                    details={"session_id": str(session_id)},
                )
            if session.user_id != user_id:
                allowed = await self._has_workspace_permission(
                    user_id=user_id,
                    workspace_id=session.workspace_id,
                    permission=Permission.CHAT_WRITE,
                )
                if not allowed:
                    logger.warning(
                        "用户无权访问会话: session_id=%s, owner=%s, requester=%s",
                        session_id,
                        session.user_id,
                        user_id,
                    )
                    raise app_forbidden(
                        "无权访问该会话",
                        code="CHAT_SESSION_FORBIDDEN",
                        details={"session_id": str(session_id)},
                    )
            logger.debug("继续已有会话: session_id=%s", session_id)
            return session

        workspace_id = await self._resolve_workspace_for_new_session(
            user_id=user_id,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )

        # 新会话标题从当前问题截断生成，避免持久化过长标题。
        title = query_text.strip()[:50] if query_text else "新对话"
        if workspace_id is None:
            session = await self.uow.chat_repo.create_session(
                user_id=user_id,
                title=title,
                kb_id=kb_id,
            )
        else:
            session = await self.uow.chat_repo.create_session(
                user_id=user_id,
                title=title,
                kb_id=kb_id,
                workspace_id=workspace_id,
            )
        logger.info(
            "创建新会话: session_id=%s, title=%s, user_id=%s",
            session.id,
            title,
            user_id,
        )
        return session

    async def _resolve_workspace_for_new_session(
        self,
        *,
        user_id: uuid.UUID,
        kb_id: uuid.UUID | None,
        workspace_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        if kb_id is not None:
            knowledge_repo = getattr(self.uow, "knowledge_repo", None)
            get_kb = getattr(knowledge_repo, "get_kb", None)
            if get_kb is None:
                return workspace_id

            kb = await get_kb(kb_id)
            if not kb:
                raise app_not_found(
                    f"知识库不存在: {kb_id}",
                    code="KNOWLEDGE_BASE_NOT_FOUND",
                    details={"kb_id": str(kb_id)},
                )

            # workspace KB 必须重新校验成员权限，避免降级/移出后仍凭 KB owner 访问。
            if kb.workspace_id is not None:
                if not await self._has_workspace_permission(
                    user_id=user_id,
                    workspace_id=kb.workspace_id,
                    permission=Permission.CHAT_WRITE,
                ):
                    raise app_forbidden(
                        "无权访问该知识库",
                        code="KNOWLEDGE_BASE_FORBIDDEN",
                        details={"kb_id": str(kb_id)},
                    )
                return kb.workspace_id

            # personal KB 没有 workspace 角色兜底，只允许 owner 使用。
            if kb.user_id == user_id:
                return kb.workspace_id  # None

            raise app_forbidden(
                "无权访问该知识库",
                code="KNOWLEDGE_BASE_FORBIDDEN",
                details={"kb_id": str(kb_id)},
            )

        if workspace_id and not await self._has_workspace_permission(
            user_id=user_id,
            workspace_id=workspace_id,
            permission=Permission.CHAT_WRITE,
        ):
            raise app_forbidden(
                "无权访问该工作区",
                code="WORKSPACE_FORBIDDEN",
                details={"workspace_id": str(workspace_id)},
            )
        return workspace_id

    async def _has_workspace_permission(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID | None,
        permission: Permission,
    ) -> bool:
        if not isinstance(workspace_id, uuid.UUID):
            return False
        return await PermissionService(self.uow).has_permission_for_user_id(
            user_id=user_id,
            workspace_id=workspace_id,
            permission=permission,
        )

    async def create_user_message(
        self,
        session_id: uuid.UUID,
        content: str,
        user_id: uuid.UUID | None = None,
        message_metadata: dict | None = None,
    ) -> ChatMessage:
        """创建已完成状态的用户消息。"""
        if user_id is None and message_metadata is None:
            message = await self.uow.chat_repo.create_message(
                session_id=session_id,
                role="user",
                content=content.strip(),
                status=MessageStatus.SUCCESS,
            )
        else:
            message = await self.uow.chat_repo.create_message(
                session_id=session_id,
                role="user",
                content=content.strip(),
                status=MessageStatus.SUCCESS,
                user_id=user_id,
                message_metadata=message_metadata,
            )
        logger.debug(
            "创建用户消息: message_id=%s, session_id=%s", message.id, session_id
        )
        return message

    async def create_assistant_message(
        self,
        session_id: uuid.UUID,
        status: MessageStatus = MessageStatus.THINKING,
        client_request_id: str | None = None,
        search_context: dict | None = None,
        user_id: uuid.UUID | None = None,
        message_metadata: dict | None = None,
    ) -> ChatMessage:
        """创建助手消息占位，后续由 workflow 回写状态。"""
        message = await self.uow.chat_repo.create_message(
            session_id=session_id,
            role="assistant",
            content="",
            status=status,
            client_request_id=client_request_id,
            search_context=search_context,
            user_id=user_id,
            message_metadata=message_metadata,
        )
        logger.debug(
            "创建助手消息: message_id=%s, session_id=%s", message.id, session_id
        )
        return message

    async def get_session(self, session_id: uuid.UUID) -> ChatSession | None:
        """读取单个会话。"""
        return await self.uow.chat_repo.get_session(session_id)

    async def get_user_sessions(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> list[ChatSession]:
        """读取用户会话列表。"""
        sessions = await self.uow.chat_repo.get_user_sessions(
            user_id=user_id,
            skip=skip,
            limit=limit,
        )
        logger.debug("获取用户会话列表: user_id=%s, count=%d", user_id, len(sessions))
        return list(sessions)

    async def get_session_messages(
        self,
        session_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ChatMessage]:
        """读取会话消息列表。"""
        messages = await self.uow.chat_repo.get_session_messages(
            session_id=session_id,
            skip=skip,
            limit=limit,
        )
        logger.debug("获取会话消息: session_id=%s, count=%d", session_id, len(messages))
        return list(messages)


class ChatMessageUpdater(BaseService[AbstractUnitOfWork]):
    """负责助手消息 THINKING/STREAMING/SUCCESS/FAILED 状态流转。"""

    def __init__(self, uow: AbstractUnitOfWork) -> None:
        super().__init__(uow)

    async def update_as_success(
        self,
        message_id: uuid.UUID,
        content: str,
        start_time: float | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        search_context: dict | None = None,
    ) -> ChatMessage:
        """把助手消息标记为成功，并保存 token/search_context。"""
        latency_ms = None
        if start_time:
            latency_ms = int((time.time() - start_time) * 1000)

        message = await self.uow.chat_repo.update_message_status(
            message_id=message_id,
            status=MessageStatus.SUCCESS,
            content=content,
            latency_ms=latency_ms,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            search_context=search_context,
        )
        if not message:
            logger.error("更新消息失败，消息不存在: message_id=%s", message_id)
            raise app_not_found(
                f"消息不存在: {message_id}",
                code="CHAT_MESSAGE_NOT_FOUND",
                details={"message_id": str(message_id)},
            )
        logger.info(
            "消息更新成功: message_id=%s, latency_ms=%s",
            message_id,
            latency_ms,
        )
        return message

    async def update_as_failed(
        self,
        message_id: uuid.UUID,
        error_content: str = "抱歉，处理您的请求时出现错误。",
    ) -> ChatMessage | None:
        """把助手消息标记为失败；消息缺失时只记录日志。"""
        message = await self.uow.chat_repo.update_message_status(
            message_id=message_id,
            status=MessageStatus.FAILED,
            content=error_content,
        )
        if message:
            logger.warning("消息更新为失败状态: message_id=%s", message_id)
        else:
            logger.error("更新失败状态时消息不存在: message_id=%s", message_id)
        return message

    async def update_as_streaming(
        self,
        message_id: uuid.UUID,
        content: str,
    ) -> ChatMessage | None:
        """保存当前已累积的流式内容。"""
        return await self.uow.chat_repo.update_message_status(
            message_id=message_id,
            status=MessageStatus.STREAMING,
            content=content,
        )
