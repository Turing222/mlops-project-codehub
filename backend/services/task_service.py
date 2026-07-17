"""Task service.

职责：创建知识库入库任务并维护任务状态。
边界：本模块只写 TaskJob 记录，不投递 TaskIQ 消息。
风险：任务访问校验基于 user_id 列，任务创建方必须写入该字段。
"""

import uuid
from datetime import UTC, datetime, timedelta

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import app_not_found
from backend.models.orm.task import (
    KNOWLEDGE_INGESTION_EVENT,
    TaskJob,
    TaskOutbox,
    TaskStatus,
)
from backend.services.base import BaseService


class TaskService(BaseService[AbstractUnitOfWork]):
    """TaskJob 创建、状态流转和访问校验服务。"""

    def __init__(self, uow: AbstractUnitOfWork) -> None:
        super().__init__(uow)

    async def create_kb_ingestion_task(
        self,
        *,
        kb_id: uuid.UUID,
        file_id: uuid.UUID,
        file_path: str,
        filename: str,
        user_id: uuid.UUID,
    ) -> TaskJob:
        return await self.uow.task_repo.create(
            action_type="KB_INGESTION",
            status=TaskStatus.PENDING,
            progress=0,
            payload={
                "kb_id": str(kb_id),
                "file_id": str(file_id),
                "file_path": file_path,
                "filename": filename,
                "user_id": str(user_id),
            },
            user_id=user_id,
            knowledge_file_id=file_id,
            knowledge_base_id=kb_id,
        )

    async def create_kb_ingestion_outbox(
        self,
        *,
        task_id: uuid.UUID,
        file_id: uuid.UUID,
        trace_context: dict[str, str] | None,
        due_at: datetime | None = None,
    ) -> TaskOutbox:
        """Persist the stable dispatch event in the caller's current UoW."""
        return await self.uow.task_outbox_repo.create(
            task_id=task_id,
            event_type=KNOWLEDGE_INGESTION_EVENT,
            payload={
                "file_id": str(file_id),
                "task_id": str(task_id),
                "trace_context": trace_context,
            },
            next_attempt_at=due_at or datetime.now(UTC),
        )

    async def create_completed_kb_ingestion_task(
        self,
        *,
        kb_id: uuid.UUID,
        file_id: uuid.UUID,
        file_path: str,
        filename: str,
        user_id: uuid.UUID,
        deduplicated: bool = False,
    ) -> TaskJob:
        return await self.uow.task_repo.create(
            action_type="KB_INGESTION",
            status=TaskStatus.COMPLETED,
            progress=100,
            payload={
                "kb_id": str(kb_id),
                "file_id": str(file_id),
                "file_path": file_path,
                "filename": filename,
                "user_id": str(user_id),
                "deduplicated": deduplicated,
            },
            user_id=user_id,
            finished_at=datetime.now(UTC),
            knowledge_file_id=file_id,
            knowledge_base_id=kb_id,
        )

    async def create_repo_analysis_task(
        self,
        *,
        run_id: uuid.UUID,
        repo_url: str,
        owner: str,
        repo: str,
        user_id: uuid.UUID,
    ) -> TaskJob:
        return await self.uow.task_repo.create(
            action_type="REPO_ANALYSIS_README",
            status=TaskStatus.PENDING,
            progress=0,
            payload={
                "run_id": str(run_id),
                "repo_url": repo_url,
                "owner": owner,
                "repo": repo,
                "user_id": str(user_id),
            },
            user_id=user_id,
        )

    async def get_by_id(self, task_id: uuid.UUID) -> TaskJob | None:
        return await self.uow.task_repo.get(task_id)

    async def mark_processing(
        self,
        *,
        task_id: uuid.UUID,
        progress: int = 0,
    ) -> TaskJob | None:
        return await self.uow.task_repo.mark_processing(
            task_id=task_id, progress=progress
        )

    async def mark_completed(
        self,
        *,
        task_id: uuid.UUID,
        progress: int = 100,
    ) -> TaskJob | None:
        return await self.uow.task_repo.mark_completed(
            task_id=task_id, progress=progress
        )

    async def mark_failed(
        self,
        *,
        task_id: uuid.UUID,
        error_log: str,
    ) -> TaskJob | None:
        return await self.uow.task_repo.mark_failed(
            task_id=task_id,
            error_log=error_log[:5000],
        )

    async def claim_kb_ingestion(
        self,
        *,
        task_id: uuid.UUID,
        file_id: uuid.UUID,
        now: datetime | None = None,
        lease_seconds: int | None = None,
    ) -> int | None:
        claimed_at = now or datetime.now(UTC)
        lease_duration = lease_seconds or ai_settings.KNOWLEDGE_INGEST_LEASE_SECONDS
        return await self.uow.task_repo.try_claim_kb_ingestion_task(
            task_id=task_id,
            file_id=file_id,
            claimed_at=claimed_at,
            lease_expires_at=claimed_at + timedelta(seconds=lease_duration),
        )

    async def heartbeat_kb_ingestion(
        self,
        *,
        task_id: uuid.UUID,
        expected_attempt: int,
        now: datetime | None = None,
        lease_seconds: int | None = None,
    ) -> bool:
        heartbeat_at = now or datetime.now(UTC)
        lease_duration = lease_seconds or ai_settings.KNOWLEDGE_INGEST_LEASE_SECONDS
        return await self.uow.task_repo.try_heartbeat_kb_ingestion_task(
            task_id=task_id,
            expected_attempt=expected_attempt,
            heartbeat_at=heartbeat_at,
            lease_expires_at=heartbeat_at + timedelta(seconds=lease_duration),
        )

    async def complete_kb_ingestion(
        self,
        *,
        task_id: uuid.UUID,
        expected_attempt: int,
        now: datetime | None = None,
    ) -> bool:
        return await self.uow.task_repo.try_complete_kb_ingestion_task(
            task_id=task_id,
            expected_attempt=expected_attempt,
            finished_at=now or datetime.now(UTC),
        )

    async def fail_kb_ingestion(
        self,
        *,
        task_id: uuid.UUID,
        error_log: str,
        expected_attempt: int | None = None,
        expected_statuses: tuple[TaskStatus, ...] = (
            TaskStatus.PENDING,
            TaskStatus.PROCESSING,
        ),
        now: datetime | None = None,
    ) -> bool:
        return await self.uow.task_repo.try_fail_kb_ingestion_task(
            task_id=task_id,
            expected_statuses=expected_statuses,
            expected_attempt=expected_attempt,
            error_log=error_log[:5000],
            finished_at=now or datetime.now(UTC),
        )

    async def ensure_user_access(self, *, task: TaskJob, user_id: uuid.UUID) -> None:
        if task.user_id is None:
            raise app_not_found("任务关联用户不存在", code="TASK_USER_NOT_FOUND")
        if task.user_id != user_id:
            raise app_not_found("任务不存在或无访问权限", code="TASK_NOT_FOUND")
