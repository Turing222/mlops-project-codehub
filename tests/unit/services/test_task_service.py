"""Task service access-control unit tests.

职责：验证 ensure_user_access 基于 user_id 列的授权判定；边界：使用 MagicMock task 与 uow，不连接数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import AppException
from backend.models.orm.task import TaskStatus
from backend.services.task_service import TaskService


@pytest.fixture
def task_service() -> TaskService:
    return TaskService(uow=MagicMock())


def _task_with_user(user_id: uuid.UUID | None) -> MagicMock:
    task = MagicMock()
    task.user_id = user_id
    return task


async def test_create_completed_kb_ingestion_task_sets_finished_at() -> None:
    create_task = AsyncMock()
    uow = MagicMock()
    uow.task_repo.create = create_task
    task_service = TaskService(cast(AbstractUnitOfWork, uow))

    await task_service.create_completed_kb_ingestion_task(
        kb_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        file_path="/tmp/existing.md",
        filename="existing.md",
        user_id=uuid.uuid4(),
        deduplicated=True,
    )

    assert create_task.await_args is not None
    kwargs = create_task.await_args.kwargs
    assert kwargs["status"] == TaskStatus.COMPLETED
    assert kwargs["finished_at"].tzinfo == UTC


async def test_ensure_user_access_passes_when_user_id_matches(
    task_service: TaskService,
) -> None:
    user_id = uuid.uuid4()

    await task_service.ensure_user_access(
        task=_task_with_user(user_id), user_id=user_id
    )


async def test_ensure_user_access_raises_not_found_when_user_id_missing(
    task_service: TaskService,
) -> None:
    with pytest.raises(AppException) as exc_info:
        await task_service.ensure_user_access(
            task=_task_with_user(None), user_id=uuid.uuid4()
        )

    assert exc_info.value.code == "TASK_USER_NOT_FOUND"


async def test_ensure_user_access_raises_not_found_when_user_id_mismatches(
    task_service: TaskService,
) -> None:
    with pytest.raises(AppException) as exc_info:
        await task_service.ensure_user_access(
            task=_task_with_user(uuid.uuid4()), user_id=uuid.uuid4()
        )

    assert exc_info.value.code == "TASK_NOT_FOUND"
