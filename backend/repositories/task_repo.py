import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.task import TaskJob, TaskStatus
from backend.repositories.base import CRUDBase


class TaskRepository:
    """任务相关的 Repository"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.crud = CRUDBase(TaskJob, session)

    async def get(self, task_id: uuid.UUID) -> TaskJob | None:
        """根据 ID 获取任务"""
        return await self.crud.get(task_id)

    async def create(
        self,
        action_type: str,
        payload: dict,
        status: TaskStatus = TaskStatus.PENDING,
        progress: int = 0,
    ) -> TaskJob:
        """创建新任务"""
        data = {
            "action_type": action_type,
            "status": status,
            "progress": progress,
            "payload": payload,
        }
        return await self.crud.create(obj_in=data)

    async def update_status(
        self,
        task_id: uuid.UUID,
        status: TaskStatus,
        progress: int | None = None,
        error_log: str | None = None,
    ) -> TaskJob | None:
        """更新任务状态和进度"""
        task = await self.get(task_id)
        if not task:
            return None

        update_data = {"status": status}
        if progress is not None:
            update_data["progress"] = progress
        if error_log is not None:
            update_data["error_log"] = error_log

        return await self.crud.update(db_obj=task, obj_in=update_data)

    async def get_by_status(
        self,
        status: TaskStatus,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[TaskJob]:
        """根据状态获取任务列表"""
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
        """
        获取用户的任务列表
        注意：TaskJob 没有直接的 user_id 字段，需要通过 payload 中的 session_id 关联查询
        或者由 Service 层在调用时传入 user_id 到 payload 中
        """
        # 暂时返回所有任务，如果需要按用户过滤，需要在 payload 中存储 user_id
        stmt = (
            select(TaskJob)
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
        """标记任务为完成状态"""
        return await self.update_status(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            progress=progress,
        )

    async def mark_failed(
        self,
        task_id: uuid.UUID,
        error_log: str,
    ) -> TaskJob | None:
        """标记任务为失败状态"""
        return await self.update_status(
            task_id=task_id,
            status=TaskStatus.FAILED,
            progress=0,
            error_log=error_log,
        )

    async def mark_processing(
        self,
        task_id: uuid.UUID,
        progress: int = 0,
    ) -> TaskJob | None:
        """标记任务为处理中状态"""
        return await self.update_status(
            task_id=task_id,
            status=TaskStatus.PROCESSING,
            progress=progress,
        )
