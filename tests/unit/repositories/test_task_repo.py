"""Task repository unit tests.

职责：验证 TaskRepository 的用户任务查询构造与状态时间戳写入；边界：使用 AsyncMock session，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.orm.task import TaskStatus
from backend.repositories.task_repo import TaskRepository


@pytest.fixture
def repo_ctx() -> tuple[TaskRepository, AsyncMock]:
    session = AsyncMock()
    repo = TaskRepository(session=session)
    return repo, session


async def test_get_user_tasks_filters_by_user_id_returns_ordered_tasks(
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
    # 用户任务过滤改用真实 user_id 列，不再走 payload JSON 提取表达式。
    assert "task_jobs.user_id =" in sql
    assert "->>" not in sql
    assert "ORDER BY task_jobs.created_at DESC" in sql


async def test_mark_processing_sets_started_at(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, _ = repo_ctx
    repo.update_status = AsyncMock(return_value=None)

    await repo.mark_processing(task_id=uuid.uuid4())

    kwargs = repo.update_status.call_args.kwargs
    assert kwargs["status"] == TaskStatus.PROCESSING
    assert kwargs["started_at"] is not None


async def test_mark_completed_sets_finished_at(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, _ = repo_ctx
    repo.update_status = AsyncMock(return_value=None)

    await repo.mark_completed(task_id=uuid.uuid4())

    kwargs = repo.update_status.call_args.kwargs
    assert kwargs["status"] == TaskStatus.COMPLETED
    assert kwargs["finished_at"] is not None


async def test_mark_failed_sets_finished_at(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, _ = repo_ctx
    repo.update_status = AsyncMock(return_value=None)

    await repo.mark_failed(task_id=uuid.uuid4(), error_log="boom")

    kwargs = repo.update_status.call_args.kwargs
    assert kwargs["status"] == TaskStatus.FAILED
    assert kwargs["finished_at"] is not None


async def test_mark_stale_kb_ingestion_tasks_failed_sets_finished_at(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    result_proxy = MagicMock()
    result_proxy.rowcount = 3
    session.execute.return_value = result_proxy

    count = await repo.mark_stale_kb_ingestion_tasks_failed(
        older_than=datetime(2026, 1, 1, tzinfo=UTC), error_log="stale"
    )

    assert count == 3
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # 超时批量失败同属终态，必须写 finished_at 以与 mark_failed 保持一致。
    assert "finished_at" in sql
