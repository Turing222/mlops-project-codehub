"""Knowledge ingestion heartbeat tests.

职责：验证 attempt-fenced immediate/periodic renewal 与 lease rejection。
边界：不连接真实数据库。
"""

import asyncio
import uuid
from unittest.mock import AsyncMock

from backend.application.knowledge.ingestion_heartbeat import (
    IngestionLeaseHeartbeat,
)


class FakeHeartbeatUow:
    def __init__(self, task_repo: AsyncMock) -> None:
        self.task_repo = task_repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


async def test_ingestion_heartbeat_renews_current_attempt_periodically() -> None:
    task_repo = AsyncMock()
    task_repo.try_heartbeat_kb_ingestion_task.return_value = True
    task_id = uuid.uuid4()
    heartbeat = IngestionLeaseHeartbeat(
        uow_factory=lambda: FakeHeartbeatUow(task_repo),
        task_id=task_id,
        expected_attempt=2,
        interval_seconds=0.01,
        lease_seconds=120,
    )

    assert await heartbeat.start() is True
    await asyncio.sleep(0.035)
    await heartbeat.stop()

    assert task_repo.try_heartbeat_kb_ingestion_task.await_count >= 3
    kwargs = task_repo.try_heartbeat_kb_ingestion_task.await_args_list[0].kwargs
    assert kwargs["task_id"] == task_id
    assert kwargs["expected_attempt"] == 2
    assert kwargs["lease_expires_at"] > kwargs["heartbeat_at"]


async def test_ingestion_heartbeat_rejection_fences_worker() -> None:
    task_repo = AsyncMock()
    task_repo.try_heartbeat_kb_ingestion_task.return_value = False
    heartbeat = IngestionLeaseHeartbeat(
        uow_factory=lambda: FakeHeartbeatUow(task_repo),
        task_id=uuid.uuid4(),
        expected_attempt=1,
        interval_seconds=0.01,
    )

    assert await heartbeat.start() is False
    assert heartbeat.lease_lost is True
    await heartbeat.stop()
    task_repo.try_heartbeat_kb_ingestion_task.assert_awaited_once()
