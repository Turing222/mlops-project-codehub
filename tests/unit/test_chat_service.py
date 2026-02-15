"""
ChatService 单元测试

覆盖 SessionManager 和 ChatMessageUpdater 的核心业务逻辑。
使用 AsyncMock 模拟 UoW 和 ChatRepository，隔离 IO 依赖。
"""

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from backend.core.exceptions import ResourceNotFound, ValidationError
from backend.models.orm.chat import ChatMessage, ChatSession, MessageStatus
from backend.services.chat_service import ChatMessageUpdater, SessionManager


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_uow():
    """构造一个 Mock UoW，其 chat_repo 的所有方法均为 AsyncMock"""
    uow = AsyncMock()
    uow.chat_repo = AsyncMock()
    return uow


@pytest.fixture
def session_manager(mock_uow):
    return SessionManager(mock_uow)


@pytest.fixture
def message_updater(mock_uow):
    return ChatMessageUpdater(mock_uow)


# ============================================================
# SessionManager Tests
# ============================================================


class TestSessionManagerEnsureSession:
    """ensure_session 方法测试"""

    @pytest.mark.asyncio
    async def test_creates_new_session_when_no_session_id(self, session_manager, mock_uow):
        """无 session_id 时应创建新会话"""
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
        # 不应调用 get_session
        mock_uow.chat_repo.get_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_session_with_default_title(self, session_manager, mock_uow):
        """query_text 为空时标题应为 '新对话'"""
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

    @pytest.mark.asyncio
    async def test_continues_existing_session(self, session_manager, mock_uow):
        """有 session_id 时应查询并返回已有会话"""
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        existing_session = MagicMock(spec=ChatSession)
        existing_session.user_id = user_id
        existing_session.id = session_id
        mock_uow.chat_repo.get_session.return_value = existing_session

        result = await session_manager.ensure_session(
            user_id=user_id,
            query_text="继续对话",
            session_id=session_id,
        )

        assert result == existing_session
        mock_uow.chat_repo.get_session.assert_called_once_with(session_id)
        mock_uow.chat_repo.create_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_session(self, session_manager, mock_uow):
        """session_id 不存在时应抛出 ResourceNotFound"""
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        mock_uow.chat_repo.get_session.return_value = None

        with pytest.raises(ResourceNotFound) as exc_info:
            await session_manager.ensure_session(
                user_id=user_id,
                query_text="",
                session_id=session_id,
            )

        assert str(session_id) in exc_info.value.message
        assert exc_info.value.details["session_id"] == str(session_id)

    @pytest.mark.asyncio
    async def test_raises_validation_error_for_wrong_user(self, session_manager, mock_uow):
        """user_id 不匹配时应抛出 ValidationError"""
        owner_id = uuid.uuid4()
        requester_id = uuid.uuid4()
        session_id = uuid.uuid4()

        existing_session = MagicMock(spec=ChatSession)
        existing_session.user_id = owner_id
        mock_uow.chat_repo.get_session.return_value = existing_session

        with pytest.raises(ValidationError) as exc_info:
            await session_manager.ensure_session(
                user_id=requester_id,
                query_text="",
                session_id=session_id,
            )

        assert "无权访问" in exc_info.value.message


class TestSessionManagerCreateMessages:
    """消息创建相关测试"""

    @pytest.mark.asyncio
    async def test_create_user_message(self, session_manager, mock_uow):
        """创建用户消息应正确传参"""
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
        )

    @pytest.mark.asyncio
    async def test_create_assistant_message(self, session_manager, mock_uow):
        """创建助手消息默认状态应为 THINKING"""
        session_id = uuid.uuid4()

        expected_msg = MagicMock(spec=ChatMessage)
        mock_uow.chat_repo.create_message.return_value = expected_msg

        result = await session_manager.create_assistant_message(session_id=session_id)

        assert result == expected_msg
        mock_uow.chat_repo.create_message.assert_called_once_with(
            session_id=session_id,
            role="assistant",
            content="",
            status=MessageStatus.THINKING,
        )


class TestSessionManagerQueries:
    """查询相关测试"""

    @pytest.mark.asyncio
    async def test_get_user_sessions(self, session_manager, mock_uow):
        """获取用户会话列表"""
        user_id = uuid.uuid4()
        sessions = [MagicMock(spec=ChatSession) for _ in range(3)]
        mock_uow.chat_repo.get_user_sessions.return_value = sessions

        result = await session_manager.get_user_sessions(user_id=user_id, skip=0, limit=10)

        assert len(result) == 3
        mock_uow.chat_repo.get_user_sessions.assert_called_once_with(
            user_id=user_id, skip=0, limit=10,
        )

    @pytest.mark.asyncio
    async def test_get_session_messages(self, session_manager, mock_uow):
        """获取会话消息列表"""
        session_id = uuid.uuid4()
        messages = [MagicMock(spec=ChatMessage) for _ in range(5)]
        mock_uow.chat_repo.get_session_messages.return_value = messages

        result = await session_manager.get_session_messages(session_id=session_id)

        assert len(result) == 5
        mock_uow.chat_repo.get_session_messages.assert_called_once_with(
            session_id=session_id, skip=0, limit=100,
        )


# ============================================================
# ChatMessageUpdater Tests
# ============================================================


class TestChatMessageUpdater:
    """ChatMessageUpdater 状态机测试"""

    @pytest.mark.asyncio
    async def test_update_as_success(self, message_updater, mock_uow):
        """更新消息为成功状态"""
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
        mock_uow.chat_repo.update_message_status.assert_called_once_with(
            message_id=message_id,
            status=MessageStatus.SUCCESS,
            content=content,
            latency_ms=None,
        )

    @pytest.mark.asyncio
    async def test_update_as_success_with_latency(self, message_updater, mock_uow):
        """更新消息为成功状态并计算延迟"""
        message_id = uuid.uuid4()
        start_time = time.time() - 0.5  # 模拟 500ms 前开始

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
        assert call_kwargs["latency_ms"] >= 400  # 至少 400ms（留点误差）

    @pytest.mark.asyncio
    async def test_update_as_success_raises_when_not_found(self, message_updater, mock_uow):
        """消息不存在时应抛出 ResourceNotFound"""
        message_id = uuid.uuid4()
        mock_uow.chat_repo.update_message_status.return_value = None

        with pytest.raises(ResourceNotFound):
            await message_updater.update_as_success(
                message_id=message_id,
                content="内容",
            )

    @pytest.mark.asyncio
    async def test_update_as_failed(self, message_updater, mock_uow):
        """更新消息为失败状态"""
        message_id = uuid.uuid4()

        updated_msg = MagicMock(spec=ChatMessage)
        mock_uow.chat_repo.update_message_status.return_value = updated_msg

        result = await message_updater.update_as_failed(message_id=message_id)

        assert result == updated_msg
        mock_uow.chat_repo.update_message_status.assert_called_once_with(
            message_id=message_id,
            status=MessageStatus.FAILED,
            content="抱歉，处理您的请求时出现错误。",
        )

    @pytest.mark.asyncio
    async def test_update_as_failed_with_custom_message(self, message_updater, mock_uow):
        """更新消息为失败状态（自定义错误内容）"""
        message_id = uuid.uuid4()
        error_msg = "服务暂时不可用"

        updated_msg = MagicMock(spec=ChatMessage)
        mock_uow.chat_repo.update_message_status.return_value = updated_msg

        result = await message_updater.update_as_failed(
            message_id=message_id,
            error_content=error_msg,
        )

        mock_uow.chat_repo.update_message_status.assert_called_once_with(
            message_id=message_id,
            status=MessageStatus.FAILED,
            content=error_msg,
        )

    @pytest.mark.asyncio
    async def test_update_as_failed_returns_none_when_not_found(self, message_updater, mock_uow):
        """消息不存在时 update_as_failed 返回 None"""
        message_id = uuid.uuid4()
        mock_uow.chat_repo.update_message_status.return_value = None

        result = await message_updater.update_as_failed(message_id=message_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_update_as_streaming(self, message_updater, mock_uow):
        """更新消息为流式输出状态"""
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
