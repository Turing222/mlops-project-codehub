"""Knowledge ingestion reconciler unit tests.

职责：覆盖 READY 收敛、过期 lease 重试和 PUBLISHED/未 claim 派发缺口。
边界：使用 fake UoW，不连接 PostgreSQL、Redis 或对象存储。
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.models.orm.knowledge import FileStatus
from backend.models.orm.task import TaskOutboxStatus, TaskStatus
from backend.services.knowledge_ingestion_recovery_service import (
    KnowledgeIngestionRecoveryService,
)


class FakeRecoveryUow:
    def __init__(self) -> None:
        self.task_repo = AsyncMock()
        self.task_outbox_repo = AsyncMock()
        self.knowledge_repo = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    @asynccontextmanager
    async def read_context(self):
        yield self


def _task(*, status: TaskStatus, attempt: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        attempt_count=attempt,
        knowledge_file_id=uuid.uuid4(),
    )


def _file(file_id: uuid.UUID, status: FileStatus) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id,
        status=status,
        kb_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        file_path="s3://bucket/demo.md",
        filename="demo.md",
    )


def _empty_scans(uow: FakeRecoveryUow) -> None:
    uow.task_repo.get_stale_kb_ingestion_tasks.return_value = []
    uow.task_repo.get_pending_kb_tasks_without_active_outbox.return_value = []
    uow.knowledge_repo.get_stale_uploaded_files_without_active_task.return_value = []


async def test_ready_file_converges_processing_task_to_completed() -> None:
    uow = FakeRecoveryUow()
    _empty_scans(uow)
    task = _task(status=TaskStatus.PROCESSING)
    uow.task_repo.get_stale_kb_ingestion_tasks.return_value = [task]
    uow.knowledge_repo.get_file.return_value = _file(
        task.knowledge_file_id, FileStatus.READY
    )
    uow.task_repo.try_reconcile_completed_kb_ingestion_task.return_value = True
    service = KnowledgeIngestionRecoveryService(uow, stale_timeout_seconds=600)

    result = await service.recover_stale_ingestions(
        now=datetime(2026, 7, 17, 12, tzinfo=UTC)
    )

    assert result.completed_task_count == 1
    assert result.failed_task_count == 0
    uow.task_repo.try_reconcile_completed_kb_ingestion_task.assert_awaited_once_with(
        task_id=task.id,
        expected_status=TaskStatus.PROCESSING,
        expected_attempt=task.attempt_count,
        finished_at=datetime(2026, 7, 17, 12, tzinfo=UTC),
    )


async def test_expired_processing_attempt_resets_file_task_and_outbox() -> None:
    uow = FakeRecoveryUow()
    _empty_scans(uow)
    task = _task(status=TaskStatus.PROCESSING, attempt=1)
    file_obj = _file(task.knowledge_file_id, FileStatus.PARSING)
    outbox = SimpleNamespace(
        id=uuid.uuid4(),
        status=TaskOutboxStatus.PUBLISHED,
        attempt_count=2,
    )
    uow.task_repo.get_stale_kb_ingestion_tasks.return_value = [task]
    uow.knowledge_repo.get_file.return_value = file_obj
    uow.task_repo.try_reset_expired_kb_ingestion_task.return_value = True
    uow.knowledge_repo.try_transition_file_status.return_value = True
    uow.task_outbox_repo.get_for_task_event.return_value = outbox
    uow.task_outbox_repo.try_prepare_replay.return_value = True
    service = KnowledgeIngestionRecoveryService(
        uow,
        stale_timeout_seconds=600,
        max_ingestion_attempts=3,
    )
    now = datetime(2026, 7, 17, 12, tzinfo=UTC)

    result = await service.recover_stale_ingestions(now=now)

    assert result.retried_task_count == 1
    uow.task_repo.try_reset_expired_kb_ingestion_task.assert_awaited_once_with(
        task_id=task.id,
        expected_attempt=1,
        lease_expired_before=now,
        legacy_updated_before=now - timedelta(seconds=600),
        error_log="知识文件入库租约超时",
    )
    uow.knowledge_repo.delete_chunks_for_file.assert_awaited_once_with(file_obj.id)
    replay_kwargs = uow.task_outbox_repo.try_prepare_replay.await_args.kwargs
    assert replay_kwargs["reset_attempts"] is True


async def test_stale_pending_task_replays_published_outbox_with_budget() -> None:
    uow = FakeRecoveryUow()
    _empty_scans(uow)
    task = _task(status=TaskStatus.PENDING, attempt=0)
    outbox = SimpleNamespace(
        id=uuid.uuid4(),
        status=TaskOutboxStatus.PUBLISHED,
        attempt_count=1,
    )
    uow.task_repo.get_pending_kb_tasks_without_active_outbox.return_value = [task]
    uow.knowledge_repo.get_file.return_value = _file(
        task.knowledge_file_id, FileStatus.UPLOADED
    )
    uow.task_outbox_repo.get_for_task_event.return_value = outbox
    uow.task_outbox_repo.try_prepare_replay.return_value = True
    service = KnowledgeIngestionRecoveryService(
        uow,
        stale_timeout_seconds=600,
        max_publish_attempts=3,
    )

    result = await service.recover_stale_ingestions(
        now=datetime(2026, 7, 17, 12, tzinfo=UTC)
    )

    assert result.replayed_outbox_count == 1
    uow.task_outbox_repo.try_prepare_replay.assert_awaited_once()
