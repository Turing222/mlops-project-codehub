"""Chat repository unit tests.

职责：验证 ChatRepository 的 session/message CRUD 和 context state 读写行为；边界：使用 AsyncMock session，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.orm.chat import MessageStatus
from backend.models.schemas.chat.context_state import ContextState
from backend.repositories.chat_repo import ChatRepository


@pytest.fixture
def mock_async_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def repo(mock_async_session: AsyncMock) -> Generator[ChatRepository, None, None]:
    with patch("backend.repositories.chat_repo.CRUDBase") as mock_crud_cls:
        instance = mock_crud_cls.return_value
        instance.get = AsyncMock()
        instance.create = AsyncMock()
        instance.update = AsyncMock()
        instance.remove = AsyncMock()
        yield ChatRepository(mock_async_session)


async def test_create_session_maps_input_to_llm_config_returns_created(
    repo: ChatRepository,
) -> None:
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    expected = MagicMock()
    repo.session_crud.create.return_value = expected

    result = await repo.create_session(
        user_id=user_id,
        title="Test Session",
        kb_id=kb_id,
        workspace_id=workspace_id,
        llm_config={"temperature": 0.7},
    )

    assert result == expected
    kwargs = repo.session_crud.create.call_args.kwargs["obj_in"]
    assert kwargs["user_id"] == user_id
    assert kwargs["title"] == "Test Session"
    assert kwargs["kb_id"] == kb_id
    assert kwargs["workspace_id"] == workspace_id
    assert kwargs["llm_config"] == {"temperature": 0.7}


async def test_get_context_state_returns_default_when_session_missing(
    repo: ChatRepository,
) -> None:
    repo.session_crud.get.return_value = None

    result = await repo.get_context_state(uuid.uuid4())

    assert result == ContextState()


async def test_get_context_state_injects_session_version_into_result(
    repo: ChatRepository,
) -> None:
    session = MagicMock()
    session.context_state = {
        "decisions": ["使用混合检索"],
        "constraints": ["不要编造"],
        "preferences": ["答案短一点"],
    }
    session.context_state_version = 7
    repo.session_crud.get.return_value = session

    result = await repo.get_context_state(uuid.uuid4())

    assert result.decisions == ["使用混合检索"]
    assert result.constraints == ["不要编造"]
    assert result.preferences == ["答案短一点"]
    assert result.version == 7


async def test_update_context_state_if_version_matches_returns_true(
    mock_async_session: AsyncMock,
) -> None:
    repo = ChatRepository(mock_async_session)
    result_proxy = MagicMock(rowcount=1)
    mock_async_session.execute.return_value = result_proxy

    updated = await repo.update_context_state_if_version_matches(
        session_id=uuid.uuid4(),
        expected_version=2,
        next_state=ContextState(decisions=["确认使用 FastAPI"], version=99),
    )

    assert updated is True
    stmt = mock_async_session.execute.call_args.args[0]
    compiled = str(stmt)
    assert "context_state_version" in compiled


async def test_update_context_state_if_version_matches_returns_false(
    mock_async_session: AsyncMock,
) -> None:
    repo = ChatRepository(mock_async_session)
    mock_async_session.execute.return_value = MagicMock(rowcount=0)

    updated = await repo.update_context_state_if_version_matches(
        session_id=uuid.uuid4(),
        expected_version=2,
        next_state=ContextState(decisions=["新决策"]),
    )

    assert updated is False


async def test_create_message_passes_extended_fields_returns_created(
    repo: ChatRepository,
) -> None:
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    expected = MagicMock()
    repo.message_crud.create.return_value = expected

    result = await repo.create_message(
        session_id=session_id,
        role="assistant",
        content="hello",
        status=MessageStatus.STREAMING,
        latency_ms=120,
        tokens_input=11,
        tokens_output=22,
        client_request_id="req-1",
        search_context={"chunks": []},
        user_id=user_id,
        message_metadata={"source": "test"},
    )

    assert result == expected
    kwargs = repo.message_crud.create.call_args.kwargs["obj_in"]
    assert kwargs["session_id"] == session_id
    assert kwargs["role"] == "assistant"
    assert kwargs["status"] == MessageStatus.STREAMING
    assert kwargs["client_request_id"] == "req-1"
    assert kwargs["tokens_input"] == 11
    assert kwargs["tokens_output"] == 22
    assert kwargs["user_id"] == user_id
    assert kwargs["message_metadata"] == {"source": "test"}


async def test_get_user_sessions_builds_ordered_paginated_query(
    mock_async_session: AsyncMock,
) -> None:
    repo = ChatRepository(mock_async_session)
    user_id = uuid.uuid4()
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = [MagicMock(), MagicMock()]
    mock_async_session.execute.return_value = result_proxy

    result = await repo.get_user_sessions(user_id=user_id, skip=2, limit=10)

    assert len(result) == 2
    mock_async_session.execute.assert_awaited_once()
    stmt = mock_async_session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "FROM chat_sessions" in sql
    assert "ORDER BY chat_sessions.updated_at DESC" in sql


async def test_update_message_status_merges_optional_fields_returns_updated(
    repo: ChatRepository,
) -> None:
    message_id = uuid.uuid4()
    existing = MagicMock()
    updated = MagicMock()
    repo.message_crud.get.return_value = existing
    repo.message_crud.update.return_value = updated

    result = await repo.update_message_status(
        message_id=message_id,
        status=MessageStatus.SUCCESS,
        content="final",
        latency_ms=321,
        tokens_input=12,
        tokens_output=34,
        search_context={"kb_id": "1"},
    )

    assert result == updated
    repo.message_crud.get.assert_awaited_once_with(message_id)
    kwargs = repo.message_crud.update.call_args.kwargs
    assert kwargs["db_obj"] == existing
    assert kwargs["obj_in"]["status"] == MessageStatus.SUCCESS
    assert kwargs["obj_in"]["tokens_input"] == 12
    assert kwargs["obj_in"]["tokens_output"] == 34


async def test_update_message_status_returns_none_when_message_missing(
    repo: ChatRepository,
) -> None:
    repo.message_crud.get.return_value = None

    result = await repo.update_message_status(
        message_id=uuid.uuid4(),
        status=MessageStatus.FAILED,
        content="err",
    )

    assert result is None
    repo.message_crud.update.assert_not_called()
