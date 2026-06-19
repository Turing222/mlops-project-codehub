"""Knowledge ingestion recovery service unit tests.

职责：验证 KnowledgeIngestionRecoveryService 的过期摄入恢复行为；边界：使用 SimpleNamespace + AsyncMock，不连接真实数据库；副作用：无。
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.services.knowledge_ingestion_recovery_service import (
    STALE_INGESTION_ERROR,
    KnowledgeIngestionRecoveryService,
)


async def test_recover_stale_ingestions_marks_files_and_tasks_as_failed() -> None:
    knowledge_repo = SimpleNamespace(
        mark_stale_ingestion_files_failed=AsyncMock(return_value=2),
    )
    task_repo = SimpleNamespace(
        mark_stale_kb_ingestion_tasks_failed=AsyncMock(return_value=1),
    )
    uow = SimpleNamespace(knowledge_repo=knowledge_repo, task_repo=task_repo)
    service = KnowledgeIngestionRecoveryService(uow, stale_timeout_seconds=600)
    now = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)

    result = await service.recover_stale_ingestions(now=now)

    assert result.failed_file_count == 2
    assert result.failed_task_count == 1
    knowledge_repo.mark_stale_ingestion_files_failed.assert_awaited_once()
    task_repo.mark_stale_kb_ingestion_tasks_failed.assert_awaited_once()
    assert (
        knowledge_repo.mark_stale_ingestion_files_failed.await_args.kwargs[
            "older_than"
        ].timestamp()
        == datetime(2026, 5, 14, 11, 50, tzinfo=UTC).timestamp()
    )
    assert (
        task_repo.mark_stale_kb_ingestion_tasks_failed.await_args.kwargs["error_log"]
        == STALE_INGESTION_ERROR
    )
