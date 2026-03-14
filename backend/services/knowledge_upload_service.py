import logging
import uuid

from fastapi import UploadFile

from backend.core.exceptions import AppError, DependencyUnavailable, ServiceError
from backend.models.orm.knowledge import FileStatus
from backend.models.schemas.knowledge_schema import KnowledgeUploadResponse
from backend.services.knowledge_service import KnowledgeService
from backend.services.task_service import TaskService
from backend.tasks.knowledge_tasks import ingest_knowledge_file_task

logger = logging.getLogger(__name__)


class KnowledgeUploadService:
    """知识库上传编排服务：保存文件、创建任务并投递异步处理。"""

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        task_service: TaskService,
    ):
        self.knowledge_service = knowledge_service
        self.task_service = task_service

    async def submit_ingestion(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        upload_file: UploadFile,
    ) -> KnowledgeUploadResponse:
        file_obj = await self.knowledge_service.save_upload_file(
            kb_id=kb_id,
            user_id=user_id,
            upload_file=upload_file,
        )
        try:
            task = await self.task_service.create_kb_ingestion_task(
                kb_id=kb_id,
                file_id=file_obj.id,
                file_path=file_obj.file_path,
                filename=file_obj.filename,
                user_id=user_id,
            )
        except AppError as exc:
            await self._handle_task_creation_failure(
                kb_id=kb_id,
                file_id=file_obj.id,
                exc=exc,
            )
            raise
        except Exception as exc:
            await self._handle_task_creation_failure(
                kb_id=kb_id,
                file_id=file_obj.id,
                exc=exc,
            )
            raise ServiceError("创建知识处理任务失败，请稍后重试") from exc

        try:
            await ingest_knowledge_file_task.kiq(str(file_obj.id), str(task.id))
        except AppError as exc:
            await self._handle_dispatch_failure(
                kb_id=kb_id,
                file_id=file_obj.id,
                task_id=task.id,
                exc=exc,
            )
            raise
        except Exception as exc:
            await self._handle_dispatch_failure(
                kb_id=kb_id,
                file_id=file_obj.id,
                task_id=task.id,
                exc=exc,
            )
            raise DependencyUnavailable("任务投递失败，请稍后重试") from exc

        return KnowledgeUploadResponse(
            task_id=task.id,
            file_id=file_obj.id,
            file_status=file_obj.status,
            task_status=task.status,
        )

    async def _handle_task_creation_failure(
        self,
        *,
        kb_id: uuid.UUID,
        file_id: uuid.UUID,
        exc: Exception,
    ) -> None:
        try:
            await self.knowledge_service.set_file_status(
                file_id=file_id,
                status=FileStatus.FAILED,
            )
        except Exception:
            logger.exception("任务创建失败后文件状态更新异常: file_id=%s", file_id)

        if isinstance(exc, AppError):
            logger.warning(
                "知识库任务创建失败: kb_id=%s, file_id=%s, error=%s",
                kb_id,
                file_id,
                exc,
            )
        else:
            logger.exception(
                "知识库任务创建失败: kb_id=%s, file_id=%s",
                kb_id,
                file_id,
            )

    async def _handle_dispatch_failure(
        self,
        *,
        kb_id: uuid.UUID,
        file_id: uuid.UUID,
        task_id: uuid.UUID,
        exc: Exception,
    ) -> None:
        try:
            await self.task_service.mark_failed(task_id=task_id, error_log=f"任务投递失败: {exc}")
        except Exception:
            logger.exception("任务失败状态更新异常: task_id=%s", task_id)

        try:
            await self.knowledge_service.set_file_status(
                file_id=file_id,
                status=FileStatus.FAILED,
            )
        except Exception:
            logger.exception("文件失败状态更新异常: file_id=%s", file_id)

        if isinstance(exc, AppError):
            logger.warning(
                "知识库任务投递失败: kb_id=%s, file_id=%s, task_id=%s, error=%s",
                kb_id,
                file_id,
                task_id,
                exc,
            )
        else:
            logger.exception(
                "知识库任务投递失败: kb_id=%s, file_id=%s, task_id=%s",
                kb_id,
                file_id,
                task_id,
            )
