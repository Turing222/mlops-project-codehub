"""Async task persistence repository.

职责：封装 TaskJob 的创建、状态流转和按用户/状态维度的查询。
边界：本模块不负责任务调度或执行，只做持久化读写。
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.task import TaskJob, TaskStatus
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
    ) -> TaskJob:
        data = {
            "action_type": action_type,
            "status": status,
            "progress": progress,
            "payload": payload,
            "user_id": user_id,
        }
        if finished_at is not None:
            data["finished_at"] = finished_at
        return await self.crud.create(obj_in=data)

    async def update_status(
        self,
        task_id: uuid.UUID,
        status: TaskStatus,
        progress: int | None = None,
        error_log: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> TaskJob | None:
        task = await self.get(task_id)
        if not task:
            return None

        update_data: dict[str, object] = {"status": status}
        if progress is not None:
            update_data["progress"] = progress
        if error_log is not None:
            update_data["error_log"] = error_log
        if started_at is not None:
            update_data["started_at"] = started_at
        if finished_at is not None:
            update_data["finished_at"] = finished_at

        return await self.crud.update(db_obj=task, obj_in=update_data)

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
        return await self.update_status(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            progress=progress,
            finished_at=datetime.now(UTC),
        )

    async def mark_failed(
        self,
        task_id: uuid.UUID,
        error_log: str,
    ) -> TaskJob | None:
        return await self.update_status(
            task_id=task_id,
            status=TaskStatus.FAILED,
            progress=0,
            error_log=error_log,
            finished_at=datetime.now(UTC),
        )

    async def mark_processing(
        self,
        task_id: uuid.UUID,
        progress: int = 0,
    ) -> TaskJob | None:
        return await self.update_status(
            task_id=task_id,
            status=TaskStatus.PROCESSING,
            progress=progress,
            started_at=datetime.now(UTC),
        )

    async def mark_stale_kb_ingestion_tasks_failed(
        self,
        *,
        older_than: datetime,
        error_log: str,
    ) -> int:
        stmt = (
            update(TaskJob)
            .where(TaskJob.action_type == "KB_INGESTION")
            .where(TaskJob.status == TaskStatus.PROCESSING)
            .where(TaskJob.updated_at < older_than)
            .values(
                status=TaskStatus.FAILED,
                progress=0,
                error_log=error_log[:5000],
                finished_at=datetime.now(UTC),
            )
        )
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)
