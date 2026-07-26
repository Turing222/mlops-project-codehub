"""Knowledge ingestion state reconciler.

职责：按结构化 File/TaskJob/TaskOutbox 关联逐对收敛孤儿、派发缺口和过期 lease。
边界：每个对象使用短事务与 CAS；不直接连接 broker，重投由 outbox relay 完成。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.models.orm.knowledge import File, FileStatus
from backend.models.orm.task import (
    KNOWLEDGE_INGESTION_EVENT,
    TaskJob,
    TaskOutboxStatus,
    TaskStatus,
)
from backend.services.base import BaseService
from backend.services.task_service import TaskService

STALE_INGESTION_ERROR = "知识文件入库租约超时"
DISPATCH_EXHAUSTED_ERROR = "知识文件入库派发预算已耗尽"
MISSING_FILE_ERROR = "知识文件记录不存在，任务已终止"


class _ReconcileConflict(RuntimeError):
    """Internal sentinel used to roll back a multi-row reconciliation CAS."""


@dataclass(slots=True)
class KnowledgeIngestionRecoveryResult:
    scanned_task_count: int = 0
    scanned_orphan_file_count: int = 0
    created_task_count: int = 0
    created_outbox_count: int = 0
    replayed_outbox_count: int = 0
    retried_task_count: int = 0
    completed_task_count: int = 0
    failed_file_count: int = 0
    failed_task_count: int = 0
    conflict_count: int = 0


class KnowledgeIngestionRecoveryService(BaseService[AbstractUnitOfWork]):
    """Converge Knowledge durable state without replaying active leases."""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        *,
        stale_timeout_seconds: int | None = None,
        max_ingestion_attempts: int | None = None,
        max_publish_attempts: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        super().__init__(uow)
        self.stale_timeout_seconds = (
            stale_timeout_seconds
            if stale_timeout_seconds is not None
            else ai_settings.KNOWLEDGE_INGEST_STALE_TIMEOUT_SECONDS
        )
        self.max_ingestion_attempts = (
            max_ingestion_attempts
            if max_ingestion_attempts is not None
            else ai_settings.KNOWLEDGE_INGEST_MAX_ATTEMPTS
        )
        self.max_publish_attempts = (
            max_publish_attempts
            if max_publish_attempts is not None
            else ai_settings.KNOWLEDGE_OUTBOX_MAX_ATTEMPTS
        )
        self.batch_size = (
            batch_size
            if batch_size is not None
            else ai_settings.KNOWLEDGE_RECOVERY_BATCH_SIZE
        )

    async def recover_stale_ingestions(
        self,
        *,
        now: datetime | None = None,
    ) -> KnowledgeIngestionRecoveryResult:
        current_time = now or datetime.now(UTC)
        legacy_older_than = current_time - timedelta(seconds=self.stale_timeout_seconds)
        async with self.uow.read_context():
            stale_tasks = await self.uow.task_repo.get_stale_kb_ingestion_tasks(
                due_at=current_time,
                legacy_older_than=legacy_older_than,
                limit=self.batch_size,
            )
            pending_gaps = (
                await self.uow.task_repo.get_pending_kb_tasks_without_active_outbox(
                    older_than=legacy_older_than,
                    limit=self.batch_size,
                )
            )
            orphan_files = await self.uow.knowledge_repo.get_stale_uploaded_files_without_active_task(
                older_than=legacy_older_than,
                limit=self.batch_size,
            )

        result = KnowledgeIngestionRecoveryResult(
            scanned_task_count=len(stale_tasks) + len(pending_gaps),
            scanned_orphan_file_count=len(orphan_files),
        )
        for task in stale_tasks:
            await self._reconcile_processing_task(
                task,
                current_time=current_time,
                legacy_older_than=legacy_older_than,
                result=result,
            )
        for task in pending_gaps:
            await self._reconcile_pending_task(
                task,
                current_time=current_time,
                result=result,
            )
        for file_obj in orphan_files:
            await self._reconcile_orphan_file(
                file_obj,
                current_time=current_time,
                result=result,
            )
        return result

    async def _reconcile_processing_task(
        self,
        task: TaskJob,
        *,
        current_time: datetime,
        legacy_older_than: datetime,
        result: KnowledgeIngestionRecoveryResult,
    ) -> None:
        file_obj = await self._get_file(task.knowledge_file_id)
        if file_obj is None:
            await self._fail_task_only(
                task,
                error_log=MISSING_FILE_ERROR,
                current_time=current_time,
                result=result,
            )
            return

        file_status = FileStatus(file_obj.status)
        if file_status == FileStatus.READY:
            async with self.uow:
                completed = (
                    await self.uow.task_repo.try_reconcile_completed_kb_ingestion_task(
                        task_id=task.id,
                        expected_status=TaskStatus.PROCESSING,
                        expected_attempt=task.attempt_count,
                        finished_at=current_time,
                    )
                )
            if completed:
                result.completed_task_count += 1
            else:
                result.conflict_count += 1
            return

        if file_status == FileStatus.FAILED:
            await self._fail_task_only(
                task,
                error_log=STALE_INGESTION_ERROR,
                current_time=current_time,
                result=result,
            )
            return

        if task.attempt_count >= self.max_ingestion_attempts:
            await self._fail_expired_pair(
                task,
                file_obj=file_obj,
                current_time=current_time,
                legacy_older_than=legacy_older_than,
                result=result,
            )
            return

        try:
            async with self.uow:
                reset = await self.uow.task_repo.try_reset_expired_kb_ingestion_task(
                    task_id=task.id,
                    expected_attempt=task.attempt_count,
                    lease_expired_before=current_time,
                    legacy_updated_before=legacy_older_than,
                    error_log=STALE_INGESTION_ERROR,
                )
                if not reset:
                    raise _ReconcileConflict
                await self.uow.knowledge_repo.delete_chunks_for_file(file_obj.id)
                file_reset = await self.uow.knowledge_repo.try_transition_file_status(
                    file_id=file_obj.id,
                    expected_previous_statuses=(file_status,),
                    target_status=FileStatus.UPLOADED,
                )
                if not file_reset:
                    raise _ReconcileConflict
                await self._prepare_task_outbox(
                    task=task,
                    file_id=file_obj.id,
                    current_time=current_time,
                    reset_publish_attempts=True,
                )
        except _ReconcileConflict:
            result.conflict_count += 1
            return
        result.retried_task_count += 1

    async def _reconcile_pending_task(
        self,
        task: TaskJob,
        *,
        current_time: datetime,
        result: KnowledgeIngestionRecoveryResult,
    ) -> None:
        file_obj = await self._get_file(task.knowledge_file_id)
        if file_obj is None:
            await self._fail_task_only(
                task,
                error_log=MISSING_FILE_ERROR,
                current_time=current_time,
                result=result,
            )
            return
        file_status = FileStatus(file_obj.status)
        if file_status == FileStatus.READY:
            async with self.uow:
                completed = (
                    await self.uow.task_repo.try_reconcile_completed_kb_ingestion_task(
                        task_id=task.id,
                        expected_status=TaskStatus.PENDING,
                        expected_attempt=task.attempt_count,
                        finished_at=current_time,
                    )
                )
            if completed:
                result.completed_task_count += 1
            else:
                result.conflict_count += 1
            return
        if file_status == FileStatus.FAILED:
            await self._fail_task_only(
                task,
                error_log=STALE_INGESTION_ERROR,
                current_time=current_time,
                result=result,
            )
            return

        try:
            async with self.uow:
                outbox = await self.uow.task_outbox_repo.get_for_task_event(
                    task_id=task.id,
                    event_type=KNOWLEDGE_INGESTION_EVENT,
                )
                if outbox is None:
                    await self._create_outbox(
                        task=task,
                        file_id=file_obj.id,
                        current_time=current_time,
                    )
                    result.created_outbox_count += 1
                    return
                outbox_status = TaskOutboxStatus(outbox.status)
                if (
                    outbox_status == TaskOutboxStatus.PUBLISHED
                    and outbox.attempt_count < self.max_publish_attempts
                ):
                    replayed = await self.uow.task_outbox_repo.try_prepare_replay(
                        outbox_id=outbox.id,
                        expected_status=TaskOutboxStatus.PUBLISHED,
                        expected_attempt=outbox.attempt_count,
                        next_attempt_at=current_time,
                    )
                    if not replayed:
                        raise _ReconcileConflict
                    result.replayed_outbox_count += 1
                    return

                failed = await self.uow.task_repo.try_fail_kb_ingestion_task(
                    task_id=task.id,
                    expected_statuses=(TaskStatus.PENDING,),
                    expected_attempt=task.attempt_count,
                    error_log=DISPATCH_EXHAUSTED_ERROR,
                    finished_at=current_time,
                )
                if not failed:
                    raise _ReconcileConflict
                await self.uow.knowledge_repo.delete_chunks_for_file(file_obj.id)
                file_failed = await self.uow.knowledge_repo.try_transition_file_status(
                    file_id=file_obj.id,
                    expected_previous_statuses=(
                        FileStatus.UPLOADED,
                        FileStatus.PARSING,
                        FileStatus.CHUNKING,
                    ),
                    target_status=FileStatus.FAILED,
                )
                if not file_failed:
                    raise _ReconcileConflict
        except _ReconcileConflict:
            result.conflict_count += 1
            return
        result.failed_task_count += 1
        result.failed_file_count += 1

    async def _reconcile_orphan_file(
        self,
        file_obj: File,
        *,
        current_time: datetime,
        result: KnowledgeIngestionRecoveryResult,
    ) -> None:
        if file_obj.owner_id is None:
            async with self.uow:
                failed = await self.uow.knowledge_repo.try_transition_file_status(
                    file_id=file_obj.id,
                    expected_previous_statuses=(FileStatus.UPLOADED,),
                    target_status=FileStatus.FAILED,
                )
            if failed:
                result.failed_file_count += 1
            else:
                result.conflict_count += 1
            return

        task_service = TaskService(self.uow)
        try:
            async with self.uow:
                task = await task_service.create_kb_ingestion_task(
                    kb_id=file_obj.kb_id,
                    file_id=file_obj.id,
                    file_path=file_obj.file_path,
                    filename=file_obj.filename,
                    user_id=file_obj.owner_id,
                )
                await task_service.create_kb_ingestion_outbox(
                    task_id=task.id,
                    file_id=file_obj.id,
                    trace_context=None,
                    due_at=current_time,
                )
        except IntegrityError:
            result.conflict_count += 1
            return
        result.created_task_count += 1
        result.created_outbox_count += 1

    async def _fail_expired_pair(
        self,
        task: TaskJob,
        *,
        file_obj: File,
        current_time: datetime,
        legacy_older_than: datetime,
        result: KnowledgeIngestionRecoveryResult,
    ) -> None:
        try:
            async with self.uow:
                failed = await self.uow.task_repo.try_fail_expired_kb_ingestion_task(
                    task_id=task.id,
                    expected_attempt=task.attempt_count,
                    lease_expired_before=current_time,
                    legacy_updated_before=legacy_older_than,
                    error_log=STALE_INGESTION_ERROR,
                    finished_at=current_time,
                )
                if not failed:
                    raise _ReconcileConflict
                await self.uow.knowledge_repo.delete_chunks_for_file(file_obj.id)
                file_failed = await self.uow.knowledge_repo.try_transition_file_status(
                    file_id=file_obj.id,
                    expected_previous_statuses=(
                        FileStatus.UPLOADED,
                        FileStatus.PARSING,
                        FileStatus.CHUNKING,
                    ),
                    target_status=FileStatus.FAILED,
                )
                if not file_failed:
                    raise _ReconcileConflict
        except _ReconcileConflict:
            result.conflict_count += 1
            return
        result.failed_task_count += 1
        result.failed_file_count += 1

    async def _fail_task_only(
        self,
        task: TaskJob,
        *,
        error_log: str,
        current_time: datetime,
        result: KnowledgeIngestionRecoveryResult,
    ) -> None:
        async with self.uow:
            failed = await self.uow.task_repo.try_fail_kb_ingestion_task(
                task_id=task.id,
                expected_statuses=(TaskStatus.PENDING, TaskStatus.PROCESSING),
                expected_attempt=task.attempt_count,
                error_log=error_log,
                finished_at=current_time,
            )
        if failed:
            result.failed_task_count += 1
        else:
            result.conflict_count += 1

    async def _prepare_task_outbox(
        self,
        *,
        task: TaskJob,
        file_id: uuid.UUID,
        current_time: datetime,
        reset_publish_attempts: bool,
    ) -> None:
        outbox = await self.uow.task_outbox_repo.get_for_task_event(
            task_id=task.id,
            event_type=KNOWLEDGE_INGESTION_EVENT,
        )
        if outbox is None:
            await self._create_outbox(
                task=task,
                file_id=file_id,
                current_time=current_time,
            )
            return
        status = TaskOutboxStatus(outbox.status)
        if status in {TaskOutboxStatus.PUBLISHED, TaskOutboxStatus.DEAD}:
            prepared = await self.uow.task_outbox_repo.try_prepare_replay(
                outbox_id=outbox.id,
                expected_status=status,
                expected_attempt=outbox.attempt_count,
                next_attempt_at=current_time,
                reset_attempts=reset_publish_attempts,
            )
            if not prepared:
                raise _ReconcileConflict

    async def _create_outbox(
        self,
        *,
        task: TaskJob,
        file_id: uuid.UUID,
        current_time: datetime,
    ) -> None:
        await self.uow.task_outbox_repo.create(
            task_id=task.id,
            event_type=KNOWLEDGE_INGESTION_EVENT,
            payload={
                "file_id": str(file_id),
                "task_id": str(task.id),
                "trace_context": None,
            },
            next_attempt_at=current_time,
        )

    async def _get_file(self, file_id: uuid.UUID | None) -> File | None:
        if file_id is None:
            return None
        async with self.uow.read_context():
            return await self.uow.knowledge_repo.get_file(file_id)
