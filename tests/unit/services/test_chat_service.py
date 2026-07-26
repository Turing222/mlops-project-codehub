"""Chat service unit tests.

职责：验证 SessionManager 和 ChatMessageUpdater 的会话管理与消息状态更新行为；边界：使用 AsyncMock 替换 UoW 和 repository，不连接真实数据库；副作用：无。
"""

import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.exceptions import AppException
from backend.models.orm.chat import ChatMessage, ChatSession, MessageStatus
from backend.services.chat_service import ChatMessageUpdater, SessionManager


@pytest.fixture
def mock_uow() -> AsyncMock:
    uow = AsyncMock()
    uow.chat_repo = AsyncMock()
    uow.knowledge_repo = AsyncMock()
    return uow


@pytest.fixture
def session_manager(mock_uow: AsyncMock) -> SessionManager:
    from backend.services.permission_service import PermissionService

    permission_service = MagicMock(spec=PermissionService)
    return SessionManager(mock_uow, permission_service)


@pytest.fixture
def message_updater(mock_uow: AsyncMock) -> ChatMessageUpdater:
    return ChatMessageUpdater(mock_uow)


class TestSessionManagerEnsureSession:
    async def test_create_or_get_session_creates_new_when_no_session_id(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        user_id = uuid.uuid4()
        query = "你好，请帮我分析一下数据"

        expected_session = MagicMock(spec=ChatSession)
        expected_session.id = uuid.uuid4()
        expected_session.title = query[:50]
        mock_uow.chat_repo.create_session.return_value = expected_session

        result = await session_manager.ensure_session(
            user_id=user_id,
            query_text=query,
            session_id=None,
        )

        assert result == expected_session
        mock_uow.chat_repo.create_session.assert_called_once_with(
            user_id=user_id,
            title=query[:50],
            kb_id=None,
        )
        mock_uow.chat_repo.get_session.assert_not_called()

    async def test_create_or_get_session_uses_default_title_when_query_empty(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        user_id = uuid.uuid4()
        expected_session = MagicMock(spec=ChatSession)
        mock_uow.chat_repo.create_session.return_value = expected_session

        await session_manager.ensure_session(
            user_id=user_id,
            query_text="",
        )

        mock_uow.chat_repo.create_session.assert_called_once_with(
            user_id=user_id,
            title="新对话",
            kb_id=None,
        )

    async def test_create_or_get_session_returns_existing_when_session_id_given(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        existing_session = MagicMock(spec=ChatSession)
        existing_session.user_id = user_id
        existing_session.id = session_id
        existing_session.kb_id = None
        existing_session.workspace_id = None
        mock_uow.chat_repo.get_session.return_value = existing_session

        result = await session_manager.ensure_session(
            user_id=user_id,
            query_text="继续对话",
            session_id=session_id,
        )

        assert result == existing_session
        mock_uow.chat_repo.get_session.assert_called_once_with(session_id)
        mock_uow.chat_repo.create_session.assert_not_called()

    async def test_create_or_get_session_raises_not_found_for_missing_session(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        mock_uow.chat_repo.get_session.return_value = None

        with pytest.raises(AppException) as exc_info:
            await session_manager.ensure_session(
                user_id=user_id,
                query_text="",
                session_id=session_id,
            )

        assert str(session_id) in exc_info.value.message
        assert exc_info.value.details["session_id"] == str(session_id)

    async def test_create_user_message_raises_validation_error_for_wrong_user(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        owner_id = uuid.uuid4()
        requester_id = uuid.uuid4()
        session_id = uuid.uuid4()

        existing_session = MagicMock(spec=ChatSession)
        existing_session.user_id = owner_id
        mock_uow.chat_repo.get_session.return_value = existing_session

        with pytest.raises(AppException) as exc_info:
            await session_manager.ensure_session(
                user_id=requester_id,
                query_text="",
                session_id=session_id,
            )

        assert "无权访问" in exc_info.value.message

    async def test_ensure_session_raises_not_found_when_kb_id_not_found(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        mock_uow.knowledge_repo.get_kb.return_value = None

        with pytest.raises(AppException) as exc_info:
            await session_manager.ensure_session(
                user_id=user_id,
                query_text="test with kb",
                kb_id=kb_id,
            )

        assert exc_info.value.code == "KNOWLEDGE_BASE_NOT_FOUND"
        assert str(kb_id) in exc_info.value.message

    # KB access re-validation for existing sessions

    async def test_ensure_session_existing_no_kb_id_allowed(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        """已有会话 + session.kb_id 非空 + 用户仍有 KB 权限 → 允许。"""
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        existing_session = MagicMock(spec=ChatSession)
        existing_session.user_id = user_id
        existing_session.id = session_id
        existing_session.kb_id = kb_id
        existing_session.workspace_id = workspace_id
        mock_uow.chat_repo.get_session.return_value = existing_session

        kb = MagicMock()
        kb.workspace_id = workspace_id
        kb.user_id = user_id
        mock_uow.knowledge_repo.get_kb.return_value = kb

        session_manager.permission_service.has_permission_for_user_id = AsyncMock(
            return_value=True
        )

        result = await session_manager.ensure_session(
            user_id=user_id,
            query_text="继续对话",
            session_id=session_id,
        )
        assert result == existing_session

    async def test_ensure_session_existing_kb_revoked_workspace(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        """已有会话 + 用户被移出 workspace → 拒绝 KB 访问。"""
        owner_id = uuid.uuid4()
        session_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        existing_session = MagicMock(spec=ChatSession)
        existing_session.user_id = owner_id
        existing_session.id = session_id
        existing_session.kb_id = kb_id
        existing_session.workspace_id = workspace_id
        mock_uow.chat_repo.get_session.return_value = existing_session

        kb = MagicMock()
        kb.workspace_id = workspace_id
        kb.user_id = owner_id
        mock_uow.knowledge_repo.get_kb.return_value = kb

        session_manager.permission_service.has_permission_for_user_id = AsyncMock(
            return_value=False
        )

        with pytest.raises(AppException) as exc_info:
            await session_manager.ensure_session(
                user_id=owner_id,
                query_text="继续对话",
                session_id=session_id,
            )
        assert exc_info.value.code == "KNOWLEDGE_BASE_FORBIDDEN"

    async def test_ensure_session_existing_personal_kb_not_owner(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        """已有会话 + personal KB owner 不是当前用户 → 拒绝。"""
        current_user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        kb_id = uuid.uuid4()

        existing_session = MagicMock(spec=ChatSession)
        existing_session.user_id = current_user_id
        existing_session.id = session_id
        existing_session.kb_id = kb_id
        existing_session.workspace_id = None
        mock_uow.chat_repo.get_session.return_value = existing_session

        kb = MagicMock()
        kb.workspace_id = None
        kb.user_id = other_user_id  # KB 属于另一个用户
        mock_uow.knowledge_repo.get_kb.return_value = kb

        with pytest.raises(AppException) as exc_info:
            await session_manager.ensure_session(
                user_id=current_user_id,
                query_text="继续对话",
                session_id=session_id,
            )
        assert exc_info.value.code == "KNOWLEDGE_BASE_FORBIDDEN"

    async def test_ensure_session_existing_no_kb_skips_revalidation(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        """已有会话 + session.kb_id=None → 跳过 KB 重新校验。"""
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        existing_session = MagicMock(spec=ChatSession)
        existing_session.user_id = user_id
        existing_session.id = session_id
        existing_session.kb_id = None
        existing_session.workspace_id = None
        mock_uow.chat_repo.get_session.return_value = existing_session

        result = await session_manager.ensure_session(
            user_id=user_id,
            query_text="继续对话",
            session_id=session_id,
        )
        assert result == existing_session
        mock_uow.knowledge_repo.get_kb.assert_not_called()

    async def test_ensure_session_existing_kb_deleted_allowed(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        """已有会话 + KB 已被删除 → 允许（graceful）。"""
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        existing_session = MagicMock(spec=ChatSession)
        existing_session.user_id = user_id
        existing_session.id = session_id
        existing_session.kb_id = uuid.uuid4()
        existing_session.workspace_id = uuid.uuid4()
        mock_uow.chat_repo.get_session.return_value = existing_session

        mock_uow.knowledge_repo.get_kb.return_value = None

        result = await session_manager.ensure_session(
            user_id=user_id,
            query_text="继续对话",
            session_id=session_id,
        )
        assert result == existing_session


class TestSessionManagerCreateMessages:
    async def test_create_user_message_returns_message(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        session_id = uuid.uuid4()
        content = "  这是一条用户消息  "

        expected_msg = MagicMock(spec=ChatMessage)
        expected_msg.id = uuid.uuid4()
        mock_uow.chat_repo.create_message.return_value = expected_msg

        result = await session_manager.create_user_message(
            session_id=session_id,
            content=content,
        )

        assert result == expected_msg
        mock_uow.chat_repo.create_message.assert_called_once_with(
            session_id=session_id,
            role="user",
            content=content.strip(),
            status=MessageStatus.SUCCESS,
            user_id=None,
            message_metadata=None,
        )

    async def test_create_assistant_message_returns_message(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        session_id = uuid.uuid4()

        expected_msg = MagicMock(spec=ChatMessage)
        mock_uow.chat_repo.create_message.return_value = expected_msg

        result = await session_manager.create_assistant_message(session_id=session_id)

        assert result == expected_msg
        mock_uow.chat_repo.create_message.assert_called_once()
        kwargs = mock_uow.chat_repo.create_message.call_args.kwargs
        assert kwargs["session_id"] == session_id
        assert kwargs["role"] == "assistant"
        assert kwargs["content"] == ""
        assert kwargs["status"] == MessageStatus.THINKING
        assert kwargs["client_request_id"] is None
        assert kwargs["search_context"] is None


class TestSessionManagerQueries:
    async def test_get_user_sessions_returns_paginated_list(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        user_id = uuid.uuid4()
        sessions = [MagicMock(spec=ChatSession) for _ in range(3)]
        mock_uow.chat_repo.get_user_sessions.return_value = sessions

        result = await session_manager.get_user_sessions(
            user_id=user_id, skip=0, limit=10
        )

        assert len(result) == 3
        mock_uow.chat_repo.get_user_sessions.assert_called_once_with(
            user_id=user_id,
            skip=0,
            limit=10,
        )

    async def test_get_session_messages_returns_paginated_list(
        self, session_manager: SessionManager, mock_uow: AsyncMock
    ) -> None:
        session_id = uuid.uuid4()
        messages = [MagicMock(spec=ChatMessage) for _ in range(5)]
        mock_uow.chat_repo.get_session_messages.return_value = messages

        result = await session_manager.get_session_messages(session_id=session_id)

        assert len(result) == 5
        mock_uow.chat_repo.get_session_messages.assert_called_once_with(
            session_id=session_id,
            skip=0,
            limit=100,
        )


class TestChatMessageUpdater:
    async def test_update_as_success_sets_status_and_metrics(
        self, message_updater: ChatMessageUpdater, mock_uow: AsyncMock
    ) -> None:
        message_id = uuid.uuid4()
        content = "AI 回复内容"

        updated_msg = MagicMock(spec=ChatMessage)
        updated_msg.id = message_id
        updated_msg.status = MessageStatus.SUCCESS
        mock_uow.chat_repo.update_message_status.return_value = updated_msg

        result = await message_updater.update_as_success(
            message_id=message_id,
            content=content,
        )

        assert result == updated_msg
        mock_uow.chat_repo.update_message_status.assert_called_once()
        kwargs = mock_uow.chat_repo.update_message_status.call_args.kwargs
        assert kwargs["message_id"] == message_id
        assert kwargs["status"] == MessageStatus.SUCCESS
        assert kwargs["content"] == content
        assert kwargs["latency_ms"] is None
        assert kwargs["tokens_input"] is None
        assert kwargs["tokens_output"] is None
        assert kwargs["search_context"] is None

    async def test_update_as_success_computes_latency_when_start_time_given(
        self, message_updater: ChatMessageUpdater, mock_uow: AsyncMock
    ) -> None:
        message_id = uuid.uuid4()
        start_time = time.time() - 0.5

        updated_msg = MagicMock(spec=ChatMessage)
        mock_uow.chat_repo.update_message_status.return_value = updated_msg

        result = await message_updater.update_as_success(
            message_id=message_id,
            content="内容",
            start_time=start_time,
        )

        assert result == updated_msg
        call_kwargs = mock_uow.chat_repo.update_message_status.call_args.kwargs
        assert call_kwargs["latency_ms"] is not None
        assert call_kwargs["latency_ms"] >= 400

    async def test_update_as_success_raises_when_not_found(
        self, message_updater: ChatMessageUpdater, mock_uow: AsyncMock
    ) -> None:
        message_id = uuid.uuid4()
        mock_uow.chat_repo.update_message_status.return_value = None

        with pytest.raises(AppException):
            await message_updater.update_as_success(
                message_id=message_id,
                content="内容",
            )

    async def test_update_as_failed_sets_status_and_error(
        self, message_updater: ChatMessageUpdater, mock_uow: AsyncMock
    ) -> None:
        message_id = uuid.uuid4()

        updated_msg = MagicMock(spec=ChatMessage)
        mock_uow.chat_repo.update_message_status.return_value = updated_msg

        result = await message_updater.update_as_failed(message_id=message_id)

        assert result == updated_msg
        mock_uow.chat_repo.update_message_status.assert_called_once_with(
            message_id=message_id,
            status=MessageStatus.FAILED,
            content="抱歉，处理您的请求时出现错误。",
            message_metadata=None,
        )

    async def test_update_as_failed_uses_custom_error_message(
        self, message_updater: ChatMessageUpdater, mock_uow: AsyncMock
    ) -> None:
        message_id = uuid.uuid4()
        error_msg = "服务暂时不可用"

        updated_msg = MagicMock(spec=ChatMessage)
        mock_uow.chat_repo.update_message_status.return_value = updated_msg

        result = await message_updater.update_as_failed(
            message_id=message_id,
            error_content=error_msg,
        )

        assert result == updated_msg
        mock_uow.chat_repo.update_message_status.assert_called_once_with(
            message_id=message_id,
            status=MessageStatus.FAILED,
            content=error_msg,
            message_metadata=None,
        )

    async def test_update_as_failed_returns_none_when_not_found(
        self, message_updater: ChatMessageUpdater, mock_uow: AsyncMock
    ) -> None:
        message_id = uuid.uuid4()
        mock_uow.chat_repo.update_message_status.return_value = None

        result = await message_updater.update_as_failed(message_id=message_id)

        assert result is None

    async def test_update_as_streaming_sets_status(
        self, message_updater: ChatMessageUpdater, mock_uow: AsyncMock
    ) -> None:
        message_id = uuid.uuid4()
        content = "部分内容..."

        updated_msg = MagicMock(spec=ChatMessage)
        mock_uow.chat_repo.update_message_status.return_value = updated_msg

        result = await message_updater.update_as_streaming(
            message_id=message_id,
            content=content,
        )

        assert result == updated_msg
        mock_uow.chat_repo.update_message_status.assert_called_once_with(
            message_id=message_id,
            status=MessageStatus.STREAMING,
            content=content,
        )
