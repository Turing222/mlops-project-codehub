"""Task repository unit tests.

职责：验证 TaskRepository 的用户任务查询构造；边界：使用 AsyncMock session，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.repositories.task_repo import TaskRepository


@pytest.fixture
def repo_ctx() -> tuple[TaskRepository, AsyncMock]:
    session = AsyncMock()
    repo = TaskRepository(session=session)
    return repo, session


async def test_get_user_tasks_filters_by_payload_user_id_returns_ordered_tasks(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    user_id = uuid.uuid4()
    expected = [MagicMock(), MagicMock()]
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = expected
    session.execute.return_value = result_proxy

    result = await repo.get_user_tasks(user_id=user_id, skip=2, limit=10)

    assert result == expected
    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "task_jobs.payload" in sql
    assert "ORDER BY task_jobs.created_at DESC" in sql
    assert str(user_id) in str(stmt.compile(compile_kwargs={"literal_binds": True}))
