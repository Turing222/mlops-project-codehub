"""Task repository unit tests.

职责：验证用户查询、单调状态 CAS、Knowledge claim attempt 与 stale 更新 SQL。
边界：使用 AsyncMock session，不连接真实数据库。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
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
    expected = [MagicMock(), MagicMock()]
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = expected
    session.execute.return_value = result_proxy

    result = await repo.get_user_tasks(user_id=uuid.uuid4(), skip=2, limit=10)

    assert result == expected
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "task_jobs.user_id =" in sql
    assert "->>" not in sql
    assert "ORDER BY task_jobs.created_at DESC" in sql


async def test_mark_processing_uses_pending_status_cas(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, _ = repo_ctx
    repo._transition_status = AsyncMock(return_value=None)

    await repo.mark_processing(task_id=uuid.uuid4())

    kwargs = repo._transition_status.await_args.kwargs
    assert kwargs["expected_statuses"] == (TaskStatus.PENDING,)
    assert kwargs["target_status"] == TaskStatus.PROCESSING
    assert kwargs["values"]["started_at"] is not None


async def test_duplicate_delivery_cannot_reopen_completed_task(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = None
    session.execute.return_value = result_proxy

    result = await repo.mark_processing(task_id=uuid.uuid4())

    assert result is None
    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "task_jobs.status IN ('pending')" in sql
    assert "status='processing'" in sql


async def test_mark_completed_requires_processing_status(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, _ = repo_ctx
    repo._transition_status = AsyncMock(return_value=None)

    await repo.mark_completed(task_id=uuid.uuid4())

    kwargs = repo._transition_status.await_args.kwargs
    assert kwargs["expected_statuses"] == (TaskStatus.PROCESSING,)
    assert kwargs["target_status"] == TaskStatus.COMPLETED
    assert kwargs["values"]["finished_at"] is not None


async def test_mark_failed_requires_nonterminal_status(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, _ = repo_ctx
    repo._transition_status = AsyncMock(return_value=None)

    await repo.mark_failed(task_id=uuid.uuid4(), error_log="boom")

    kwargs = repo._transition_status.await_args.kwargs
    assert kwargs["expected_statuses"] == (
        TaskStatus.PENDING,
        TaskStatus.PROCESSING,
    )
    assert kwargs["target_status"] == TaskStatus.FAILED


async def test_kb_claim_increments_attempt_and_matches_structured_file(
    repo_ctx: tuple[TaskRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = 2
    session.execute.return_value = result_proxy
    now = datetime(2026, 7, 17, tzinfo=UTC)
    file_id = uuid.uuid4()

    attempt = await repo.try_claim_kb_ingestion_task(
        task_id=uuid.uuid4(),
        file_id=file_id,
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )

    assert attempt == 2
    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "task_jobs.knowledge_file_id =" in sql
    assert "task_jobs.status = 'pending'" in sql
    assert "attempt_count=(task_jobs.attempt_count + 1)" in sql
