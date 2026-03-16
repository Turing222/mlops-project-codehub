import uuid

from backend.core.exceptions import ResourceNotFound
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.task import TaskJob, TaskStatus
from backend.services.base import BaseService


class TaskService(BaseService[AbstractUnitOfWork]):
    def __init__(self, uow: AbstractUnitOfWork):
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

    async def ensure_user_access(self, *, task: TaskJob, user_id: uuid.UUID) -> None:
        payload = task.payload or {}
        payload_user_id = payload.get("user_id")
        if payload_user_id is None:
            raise ResourceNotFound("任务关联用户不存在")
        if str(user_id) != str(payload_user_id):
            raise ResourceNotFound("任务不存在或无访问权限")
