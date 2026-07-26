"""Knowledge outbox relay tests.

职责：验证稳定 message identity、发布确认、失败回退与预算耗尽。
边界：使用 fake UoW/dispatcher，不连接 PostgreSQL 或 Redis。
"""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from backend.application.knowledge.outbox_relay import (
    PUBLISH_EXHAUSTED_ERROR,
    KnowledgeOutboxRelayService,
)
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.models.orm.knowledge import FileStatus
from backend.models.orm.task import (
    KNOWLEDGE_INGESTION_EVENT,
    TaskOutboxStatus,
    TaskStatus,
)


class FakeOutboxUow:
    def __init__(self, repo: AsyncMock) -> None:
        self.task_outbox_repo = repo
        self.task_repo = AsyncMock()
        self.knowledge_repo = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    @asynccontextmanager
    async def read_context(self):
        yield self


def _outbox(*, attempt: int = 1) -> SimpleNamespace:
    task_id = uuid.uuid4()
    return SimpleNamespace(
        id=uuid.uuid4(),
        task_id=task_id,
        event_type=KNOWLEDGE_INGESTION_EVENT,
        payload={
            "file_id": str(uuid.uuid4()),
            "task_id": str(task_id),
            "trace_context": {"traceparent": "00-test"},
        },
        status=TaskOutboxStatus.PUBLISHING,
        attempt_count=attempt,
        next_attempt_at=None,
        lease_expires_at=None,
    )


async def test_relay_publishes_with_outbox_as_stable_message_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = _outbox()
    repo = AsyncMock()
    repo.claim_due_batch.return_value = [row]
    repo.get_exhausted_due.return_value = []
    repo.try_mark_published.return_value = True
    dispatcher = AsyncMock()
    service = KnowledgeOutboxRelayService(
        uow=cast(AbstractUnitOfWork, FakeOutboxUow(repo)),
        dispatcher=dispatcher,
        batch_size=10,
    )
    caplog.set_level(
        logging.INFO,
        logger="backend.application.knowledge.outbox_relay",
    )

    result = await service.relay_due(now=datetime(2026, 7, 17, tzinfo=UTC))

    assert result.claimed_count == 1
    assert result.published_count == 1
    dispatcher.enqueue_ingestion.assert_awaited_once_with(
        row.payload["file_id"],
        row.payload["task_id"],
        row.payload["trace_context"],
        outbox_id=str(row.id),
        message_id=str(row.id),
    )
    repo.try_mark_published.assert_awaited_once()
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "knowledge_outbox_published"
    )
    fields = record.__dict__
    assert fields["outbox_id"] == str(row.id)
    assert fields["outbox_status"] == str(TaskOutboxStatus.PUBLISHED)
    assert fields["previous_outbox_status"] == str(row.status)


async def test_relay_broker_failure_releases_event_for_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = _outbox()
    repo = AsyncMock()
    repo.claim_due_batch.return_value = [row]
    repo.get_exhausted_due.return_value = []
    repo.try_release_for_retry.return_value = True
    dispatcher = AsyncMock()
    dispatcher.enqueue_ingestion.side_effect = ConnectionError("redis down")
    service = KnowledgeOutboxRelayService(
        uow=cast(AbstractUnitOfWork, FakeOutboxUow(repo)),
        dispatcher=dispatcher,
        retry_seconds=30,
    )
    caplog.set_level(
        logging.ERROR,
        logger="backend.application.knowledge.outbox_relay",
    )

    result = await service.relay_due(now=datetime(2026, 7, 17, tzinfo=UTC))

    assert result.retry_count == 1
    repo.try_release_for_retry.assert_awaited_once()
    kwargs = repo.try_release_for_retry.await_args.kwargs
    assert kwargs["last_error"] == "ConnectionError: broker publish failed"
    repo.try_mark_published.assert_not_awaited()
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "knowledge_outbox_publish_failed"
    )
    fields = record.__dict__
    assert fields["task_name"] == "relay_knowledge_ingestion_outbox"
    assert fields["outbox_id"] == str(row.id)
    assert fields["job_id"] == str(row.task_id)
    assert fields["task_id"] == str(row.task_id)
    assert fields["event_type"] == row.event_type
    assert fields["outbox_status"] == str(row.status)
    assert fields["previous_outbox_status"] == str(row.status)
    assert fields["publish_attempt"] == row.attempt_count


async def test_relay_marks_due_publish_budget_as_dead(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = _outbox(attempt=3)
    row.status = TaskOutboxStatus.PENDING
    repo = AsyncMock()
    repo.claim_due_batch.return_value = []
    repo.get_exhausted_due.return_value = [row]
    repo.try_mark_dead.return_value = True
    service = KnowledgeOutboxRelayService(
        uow=cast(AbstractUnitOfWork, FakeOutboxUow(repo)),
        dispatcher=AsyncMock(),
        max_attempts=3,
    )
    caplog.set_level(
        logging.ERROR,
        logger="backend.application.knowledge.outbox_relay",
    )

    result = await service.relay_due(now=datetime(2026, 7, 17, tzinfo=UTC))

    assert result.dead_count == 1
    repo.try_mark_dead.assert_awaited_once()
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "knowledge_outbox_dead"
    )
    fields = record.__dict__
    assert fields["outbox_id"] == str(row.id)
    assert fields["task_id"] == str(row.task_id)
    assert fields["outbox_status"] == str(TaskOutboxStatus.DEAD)
    assert fields["previous_outbox_status"] == str(row.status)
    assert fields["publish_attempt"] == row.attempt_count
    assert fields["attempt"] == row.attempt_count
    assert fields["error_code"] == PUBLISH_EXHAUSTED_ERROR
    assert isinstance(fields["duration_ms"], float)


async def test_manual_dead_replay_reopens_failed_task_file_and_outbox_atomically() -> (
    None
):
    row = _outbox(attempt=3)
    row.status = TaskOutboxStatus.DEAD
    repo = AsyncMock()
    repo.get.return_value = row
    repo.try_prepare_replay.return_value = True
    uow = FakeOutboxUow(repo)
    uow.task_repo.get.return_value = SimpleNamespace(
        id=row.task_id,
        status=TaskStatus.FAILED,
        attempt_count=1,
    )
    uow.task_repo.try_prepare_failed_kb_ingestion_replay.return_value = True
    uow.knowledge_repo.get_file.return_value = SimpleNamespace(
        id=uuid.UUID(row.payload["file_id"]),
        status=FileStatus.FAILED,
    )
    uow.knowledge_repo.try_transition_file_status.return_value = True
    service = KnowledgeOutboxRelayService(
        uow=cast(AbstractUnitOfWork, uow),
        dispatcher=AsyncMock(),
    )

    replayed = await service.replay_dead(
        outbox_id=row.id,
        expected_attempt=3,
        now=datetime(2026, 7, 17, tzinfo=UTC),
    )

    assert replayed is True
    uow.task_repo.try_prepare_failed_kb_ingestion_replay.assert_awaited_once()
    uow.knowledge_repo.delete_chunks_for_file.assert_awaited_once()
    repo.try_prepare_replay.assert_awaited_once()
