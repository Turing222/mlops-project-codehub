"""Async task persistence repository.

职责：封装 TaskJob 的创建、状态流转和按用户/状态维度的查询。
边界：本模块不负责任务调度或执行，只做持久化读写。
"""

import uuid
from collections.abc import Collection, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.task import (
    KNOWLEDGE_INGESTION_EVENT,
    TaskJob,
    TaskOutbox,
    TaskOutboxStatus,
    TaskStatus,
)
from backend.repositories.base import CRUDBase


class TaskRepository:
    """异步任务的持久化操作，组合 CRUDBase 管理状态流转。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.crud: CRUDBase[TaskJob, BaseModel, BaseModel] = CRUDBase(TaskJob, session)

    async def get(self, task_id: uuid.UUID) -> TaskJob | None:
        return await self.crud.get(task_id)

    async def create(
        self,
        action_type: str,
        payload: dict,
        status: TaskStatus = TaskStatus.PENDING,
        progress: int = 0,
        user_id: uuid.UUID | None = None,
        finished_at: datetime | None = None,
        knowledge_file_id: uuid.UUID | None = None,
        knowledge_base_id: uuid.UUID | None = None,
    ) -> TaskJob:
        data = {
            "action_type": action_type,
            "status": status,
            "progress": progress,
            "payload": payload,
            "user_id": user_id,
            "knowledge_file_id": knowledge_file_id,
            "knowledge_base_id": knowledge_base_id,
        }
        if finished_at is not None:
            data["finished_at"] = finished_at
        return await self.crud.create(obj_in=data)

    async def get_by_status(
        self,
        status: TaskStatus,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[TaskJob]:
        stmt = (
            select(TaskJob)
            .where(TaskJob.status == status)
            .order_by(TaskJob.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_user_tasks(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> Sequence[TaskJob]:
        stmt = (
            select(TaskJob)
            .where(TaskJob.user_id == user_id)
            .order_by(TaskJob.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def mark_completed(
        self,
        task_id: uuid.UUID,
        progress: int = 100,
    ) -> TaskJob | None:
        return await self._transition_status(
            task_id=task_id,
            expected_statuses=(TaskStatus.PROCESSING,),
            target_status=TaskStatus.COMPLETED,
            values={
                "progress": progress,
                "finished_at": datetime.now(UTC),
                "lease_expires_at": None,
            },
        )

    async def mark_failed(
        self,
        task_id: uuid.UUID,
        error_log: str,
    ) -> TaskJob | None:
        return await self._transition_status(
            task_id=task_id,
            expected_statuses=(TaskStatus.PENDING, TaskStatus.PROCESSING),
            target_status=TaskStatus.FAILED,
            values={
                "progress": 0,
                "error_log": error_log,
                "finished_at": datetime.now(UTC),
                "lease_expires_at": None,
            },
        )

    async def mark_processing(
        self,
        task_id: uuid.UUID,
        progress: int = 0,
    ) -> TaskJob | None:
        started_at = datetime.now(UTC)
        return await self._transition_status(
            task_id=task_id,
            expected_statuses=(TaskStatus.PENDING,),
            target_status=TaskStatus.PROCESSING,
            values={
                "progress": progress,
                "started_at": started_at,
                "heartbeat_at": started_at,
            },
        )

    async def _transition_status(
        self,
        *,
        task_id: uuid.UUID,
        expected_statuses: Collection[TaskStatus],
        target_status: TaskStatus,
        values: dict[str, object],
    ) -> TaskJob | None:
        """Apply one monotonic repository transition without a read/write race."""
        stmt = (
            update(TaskJob)
            .where(
                TaskJob.id == task_id,
                TaskJob.status.in_(tuple(expected_statuses)),
            )
            .values(status=target_status, **values)
            .returning(TaskJob)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def try_claim_kb_ingestion_task(
        self,
        *,
        task_id: uuid.UUID,
        file_id: uuid.UUID,
        claimed_at: datetime,
        lease_expires_at: datetime,
    ) -> int | None:
        """CAS a stable Knowledge job from PENDING to PROCESSING."""
        stmt = (
            update(TaskJob)
            .where(
                TaskJob.id == task_id,
                TaskJob.action_type == "KB_INGESTION",
                TaskJob.knowledge_file_id == file_id,
                TaskJob.status == TaskStatus.PENDING,
            )
            .values(
                status=TaskStatus.PROCESSING,
                progress=5,
                attempt_count=TaskJob.attempt_count + 1,
                error_log=None,
                started_at=claimed_at,
                finished_at=None,
                heartbeat_at=claimed_at,
                lease_expires_at=lease_expires_at,
            )
            .returning(TaskJob.attempt_count)
        )
        result = await self.session.execute(stmt)
        attempt = result.scalar_one_or_none()
        return int(attempt) if attempt is not None else None

    async def try_heartbeat_kb_ingestion_task(
        self,
        *,
        task_id: uuid.UUID,
        expected_attempt: int,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        stmt = (
            update(TaskJob)
            .where(
                TaskJob.id == task_id,
                TaskJob.action_type == "KB_INGESTION",
                TaskJob.status == TaskStatus.PROCESSING,
                TaskJob.attempt_count == expected_attempt,
            )
            .values(
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
            )
            .returning(TaskJob.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_complete_kb_ingestion_task(
        self,
        *,
        task_id: uuid.UUID,
        expected_attempt: int,
        finished_at: datetime,
    ) -> bool:
        stmt = (
            update(TaskJob)
            .where(
                TaskJob.id == task_id,
                TaskJob.action_type == "KB_INGESTION",
                TaskJob.status == TaskStatus.PROCESSING,
                TaskJob.attempt_count == expected_attempt,
            )
            .values(
                status=TaskStatus.COMPLETED,
                progress=100,
                finished_at=finished_at,
                heartbeat_at=finished_at,
                lease_expires_at=None,
                error_log=None,
            )
            .returning(TaskJob.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_reconcile_completed_kb_ingestion_task(
        self,
        *,
        task_id: uuid.UUID,
        expected_status: TaskStatus,
        expected_attempt: int,
        finished_at: datetime,
    ) -> bool:
        if expected_status not in {TaskStatus.PENDING, TaskStatus.PROCESSING}:
            raise ValueError("expected_status must be nonterminal")
        stmt = (
            update(TaskJob)
            .where(
                TaskJob.id == task_id,
                TaskJob.action_type == "KB_INGESTION",
                TaskJob.status == expected_status,
                TaskJob.attempt_count == expected_attempt,
            )
            .values(
                status=TaskStatus.COMPLETED,
                progress=100,
                finished_at=finished_at,
                heartbeat_at=finished_at,
                lease_expires_at=None,
                error_log=None,
            )
            .returning(TaskJob.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_prepare_failed_kb_ingestion_replay(
        self,
        *,
        task_id: uuid.UUID,
        expected_attempt: int,
    ) -> bool:
        stmt = (
            update(TaskJob)
            .where(
                TaskJob.id == task_id,
                TaskJob.action_type == "KB_INGESTION",
                TaskJob.status == TaskStatus.FAILED,
                TaskJob.attempt_count == expected_attempt,
            )
            .values(
                status=TaskStatus.PENDING,
                progress=0,
                error_log=None,
                started_at=None,
                finished_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
            )
            .returning(TaskJob.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_fail_kb_ingestion_task(
        self,
        *,
        task_id: uuid.UUID,
        expected_statuses: Collection[TaskStatus],
        error_log: str,
        finished_at: datetime,
        expected_attempt: int | None = None,
    ) -> bool:
        conditions = [
            TaskJob.id == task_id,
            TaskJob.action_type == "KB_INGESTION",
            TaskJob.status.in_(tuple(expected_statuses)),
        ]
        if expected_attempt is not None:
            conditions.append(TaskJob.attempt_count == expected_attempt)
        stmt = (
            update(TaskJob)
            .where(*conditions)
            .values(
                status=TaskStatus.FAILED,
                progress=0,
                error_log=error_log[:5000],
                finished_at=finished_at,
                lease_expires_at=None,
            )
            .returning(TaskJob.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_reset_expired_kb_ingestion_task(
        self,
        *,
        task_id: uuid.UUID,
        expected_attempt: int,
        lease_expired_before: datetime,
        legacy_updated_before: datetime,
        error_log: str,
    ) -> bool:
        stmt = (
            update(TaskJob)
            .where(
                TaskJob.id == task_id,
                TaskJob.action_type == "KB_INGESTION",
                TaskJob.status == TaskStatus.PROCESSING,
                TaskJob.attempt_count == expected_attempt,
                or_(
                    TaskJob.lease_expires_at <= lease_expired_before,
                    and_(
                        TaskJob.lease_expires_at.is_(None),
                        TaskJob.updated_at <= legacy_updated_before,
                    ),
                ),
            )
            .values(
                status=TaskStatus.PENDING,
                progress=0,
                error_log=error_log[:5000],
                started_at=None,
                finished_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
            )
            .returning(TaskJob.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_fail_expired_kb_ingestion_task(
        self,
        *,
        task_id: uuid.UUID,
        expected_attempt: int,
        lease_expired_before: datetime,
        legacy_updated_before: datetime,
        error_log: str,
        finished_at: datetime,
    ) -> bool:
        stmt = (
            update(TaskJob)
            .where(
                TaskJob.id == task_id,
                TaskJob.action_type == "KB_INGESTION",
                TaskJob.status == TaskStatus.PROCESSING,
                TaskJob.attempt_count == expected_attempt,
                or_(
                    TaskJob.lease_expires_at <= lease_expired_before,
                    and_(
                        TaskJob.lease_expires_at.is_(None),
                        TaskJob.updated_at <= legacy_updated_before,
                    ),
                ),
            )
            .values(
                status=TaskStatus.FAILED,
                progress=0,
                error_log=error_log[:5000],
                finished_at=finished_at,
                lease_expires_at=None,
            )
            .returning(TaskJob.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_stale_kb_ingestion_tasks(
        self,
        *,
        due_at: datetime,
        legacy_older_than: datetime,
        limit: int,
    ) -> Sequence[TaskJob]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        stmt = (
            select(TaskJob)
            .where(
                TaskJob.action_type == "KB_INGESTION",
                TaskJob.status == TaskStatus.PROCESSING,
                or_(
                    TaskJob.lease_expires_at <= due_at,
                    and_(
                        TaskJob.lease_expires_at.is_(None),
                        TaskJob.updated_at <= legacy_older_than,
                    ),
                ),
            )
            .order_by(TaskJob.updated_at.asc(), TaskJob.id.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_pending_kb_tasks_without_active_outbox(
        self,
        *,
        older_than: datetime,
        limit: int,
    ) -> Sequence[TaskJob]:
        """Find accepted jobs lacking a due publisher or an active worker lease."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        active_outbox = and_(
            TaskOutbox.task_id == TaskJob.id,
            TaskOutbox.event_type == KNOWLEDGE_INGESTION_EVENT,
            TaskOutbox.status.in_(
                (TaskOutboxStatus.PENDING, TaskOutboxStatus.PUBLISHING)
            ),
        )
        stmt = (
            select(TaskJob)
            .outerjoin(TaskOutbox, active_outbox)
            .where(
                TaskJob.action_type == "KB_INGESTION",
                TaskJob.status == TaskStatus.PENDING,
                TaskJob.knowledge_file_id.is_not(None),
                TaskJob.updated_at <= older_than,
                TaskOutbox.id.is_(None),
            )
            .order_by(TaskJob.updated_at.asc(), TaskJob.id.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
