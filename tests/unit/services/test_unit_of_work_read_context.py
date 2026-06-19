"""Unit of Work read context unit tests.

职责：验证 SQLAlchemyUnitOfWork read_context 的会话管理、异常回滚和嵌套防护行为；边界：使用 DummySession，不连接真实数据库；副作用：无。
"""

from unittest.mock import AsyncMock

import pytest

from backend.services import unit_of_work as uow_module
from backend.services.unit_of_work import SQLAlchemyUnitOfWork


class DummySession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()


class DummyRepository:
    def __init__(self, session: DummySession) -> None:
        self.session = session


@pytest.fixture(autouse=True)
def patch_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AccessRepository",
        "AuditRepository",
        "ChatRepository",
        "KnowledgeRepository",
        "TaskRepository",
        "UserRepository",
    ):
        monkeypatch.setattr(uow_module, name, DummyRepository)


async def test_read_context_closes_without_commit_returns_none() -> None:
    session = DummySession()
    uow = SQLAlchemyUnitOfWork(lambda: session)

    async with uow.read_context():
        assert uow.session is session
        assert uow.chat_repo.session is session

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once()


async def test_read_context_rolls_back_on_exception_and_raises() -> None:
    session = DummySession()
    uow = SQLAlchemyUnitOfWork(lambda: session)

    with pytest.raises(ValueError, match="boom"):
        async with uow.read_context():
            raise ValueError("boom")

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


async def test_read_context_inside_active_uow_raises_runtime_error() -> None:
    session = DummySession()
    uow = SQLAlchemyUnitOfWork(lambda: session)

    async with uow:
        with pytest.raises(
            RuntimeError, match="Cannot open read_context inside an active UoW"
        ):
            async with uow.read_context():
                pass


async def test_read_context_exit_sets_session_to_none_on_cleanup() -> None:
    session = DummySession()
    uow = SQLAlchemyUnitOfWork(lambda: session)

    async with uow.read_context():
        assert uow._session is session

    assert uow._session is None
