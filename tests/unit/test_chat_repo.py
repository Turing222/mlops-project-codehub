import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.engine import Result

from backend.models.orm.chat import ChatMessage, ChatSession, MessageStatus
from backend.repositories.chat_repo import ChatRepository


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def repo(mock_session):
    # 我们这里不 patch CRUDBase，而是让它真实实例化，但传入 mock_session
    # 这样可以测试 ChatRepository 是否正确使用了 CRUDBase
    # 或者，如果想隔离 CRUDBase，可以 patch 它
    # 为了测试 ChatRepository 的逻辑，patch CRUDBase 更纯粹
    with patch("backend.repositories.chat_repo.CRUDBase") as MockCRUDBase:
        # 确保 CRUDBase 的实例方法是异步的
        instance = MockCRUDBase.return_value
        instance.get = AsyncMock()
        instance.create = AsyncMock()
        instance.update = AsyncMock()
        instance.remove = AsyncMock()

        repo_instance = ChatRepository(mock_session)
        yield repo_instance


@pytest.mark.asyncio
async def test_create_session(repo):
    # Setup
    user_id = uuid.uuid4()
    title = "Test Session"
    kb_id = uuid.uuid4()
    model_config = {"temperature": 0.7}

    # Configure mock
    mock_session_crud = repo.session_crud
    expected_session = ChatSession(
        id=uuid.uuid4(),
        user_id=user_id,
        title=title,
        kb_id=kb_id,
        model_config=model_config,
    )
    mock_session_crud.create.return_value = expected_session

    # Execute
    result = await repo.create_session(
        user_id=user_id, title=title, kb_id=kb_id, model_config=model_config
    )

    # Assert
    assert result == expected_session
    mock_session_crud.create.assert_called_once()
    call_kwargs = mock_session_crud.create.call_args.kwargs
    assert call_kwargs["obj_in"]["user_id"] == user_id
    assert call_kwargs["obj_in"]["title"] == title
    assert call_kwargs["obj_in"]["kb_id"] == kb_id
    assert call_kwargs["obj_in"]["model_config"] == model_config


@pytest.mark.asyncio
async def test_get_user_sessions(mock_session):
    # 这里不能用 repo fixture，因为我们需要 mock_session 被真实调用
    # 而 repo fixture patch 了 CRUDBase，虽然 get_user_sessions 不用 CRUDBase，
    # 但为了清晰，我们直接实例化 ChatRepository

    # Setup
    repo = ChatRepository(mock_session)
    user_id = uuid.uuid4()

    # Mock database result
    mock_result = MagicMock(spec=Result)
    sessions = [
        ChatSession(id=uuid.uuid4(), title="Session 1", user_id=user_id),
        ChatSession(id=uuid.uuid4(), title="Session 2", user_id=user_id),
    ]
    mock_result.scalars.return_value.all.return_value = sessions
    mock_session.execute.return_value = mock_result

    # Execute
    result = await repo.get_user_sessions(user_id, skip=0, limit=10)

    # Assert
    assert len(result) == 2
    assert result == sessions
    mock_session.execute.assert_called_once()

    # Verify query structure
    args, _ = mock_session.execute.call_args
    stmt = args[0]
    sql_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # UUID 可能会被编译为带引号或不带引号，带连字符或不带连字符
    user_id_hex = user_id.hex
    assert (
        f"'{user_id}'" in sql_str
        or f"{user_id}" in sql_str
        or f"'{user_id_hex}'" in sql_str
        or f"{user_id_hex}" in sql_str
    )
    # 注意：SQLAlchemy compile output 可能会因版本/方言不同而异，这里主要检查关键字
    assert "ORDER BY chat_sessions.updated_at DESC" in str(stmt)


@pytest.mark.asyncio
async def test_create_message(repo):
    # Setup
    session_id = uuid.uuid4()
    role = "user"
    content = "Hello"
    status = MessageStatus.SUCCESS
    latency_ms = 100

    mock_message_crud = repo.message_crud
    expected_message = ChatMessage(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        status=status,
        latency_ms=latency_ms,
    )
    mock_message_crud.create.return_value = expected_message

    # Execute
    result = await repo.create_message(
        session_id=session_id,
        role=role,
        content=content,
        status=status,
        latency_ms=latency_ms,
    )

    # Assert
    assert result == expected_message
    mock_message_crud.create.assert_called_once()
    call_kwargs = mock_message_crud.create.call_args.kwargs
    assert call_kwargs["obj_in"]["session_id"] == session_id
    assert call_kwargs["obj_in"]["role"] == role
    assert call_kwargs["obj_in"]["content"] == content
    assert call_kwargs["obj_in"]["status"] == status


@pytest.mark.asyncio
async def test_get_session_messages(mock_session):
    repo = ChatRepository(mock_session)
    session_id = uuid.uuid4()

    mock_result = MagicMock(spec=Result)
    messages = [
        ChatMessage(
            id=uuid.uuid4(),
            session_id=session_id,
            content="Hi",
            created_at="2023-01-01",
        ),
        ChatMessage(
            id=uuid.uuid4(),
            session_id=session_id,
            content="Hello",
            created_at="2023-01-02",
        ),
    ]
    mock_result.scalars.return_value.all.return_value = messages
    mock_session.execute.return_value = mock_result

    # Execute
    result = await repo.get_session_messages(session_id)

    # Assert
    assert len(result) == 2
    assert result == messages
    mock_session.execute.assert_called_once()

    # Verify ordering
    args, _ = mock_session.execute.call_args
    stmt = args[0]
    assert "ORDER BY chat_messages.created_at ASC" in str(stmt)


@pytest.mark.asyncio
async def test_update_message_status(repo):
    # Setup
    message_id = uuid.uuid4()
    new_status = MessageStatus.SUCCESS
    new_content = "Updated content"
    new_latency = 200

    # Mock existing message
    existing_message = ChatMessage(id=message_id, status=MessageStatus.THINKING)
    repo.message_crud.get.return_value = existing_message

    # Mock update result
    updated_message = ChatMessage(
        id=message_id, status=new_status, content=new_content, latency_ms=new_latency
    )
    repo.message_crud.update.return_value = updated_message

    # Execute
    result = await repo.update_message_status(
        message_id, status=new_status, content=new_content, latency_ms=new_latency
    )

    # Assert
    assert result == updated_message
    repo.message_crud.get.assert_called_once_with(message_id)
    repo.message_crud.update.assert_called_once()
    call_kwargs = repo.message_crud.update.call_args.kwargs
    assert call_kwargs["db_obj"] == existing_message
    assert call_kwargs["obj_in"]["status"] == new_status
    assert call_kwargs["obj_in"]["content"] == new_content
    assert call_kwargs["obj_in"]["latency_ms"] == new_latency


@pytest.mark.asyncio
async def test_update_message_status_not_found(repo):
    message_id = uuid.uuid4()
    repo.message_crud.get.return_value = None

    result = await repo.update_message_status(message_id, MessageStatus.SUCCESS)

    assert result is None
    repo.message_crud.get.assert_called_once_with(message_id)
    repo.message_crud.update.assert_not_called()
