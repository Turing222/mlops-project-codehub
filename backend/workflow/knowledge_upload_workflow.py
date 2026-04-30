import logging
import uuid

from fastapi import UploadFile

from backend.core.exceptions import (
    AppException,
    app_dependency_unavailable,
    app_service_error,
)
from backend.core.trace_utils import (
    inject_trace_context,
    set_span_attributes,
    trace_span,
)
from backend.models.orm.knowledge import File, FileStatus
from backend.models.schemas.knowledge_schema import KnowledgeUploadResponse
from backend.services.knowledge_service import KnowledgeService
from backend.services.task_service import TaskService
from backend.tasks.knowledge_tasks import ingest_knowledge_file_task

logger = logging.getLogger(__name__)


class KnowledgeUploadWorkflow:
    """知识库上传工作流：保存文件、创建任务并投递异步处理。"""

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        task_service: TaskService,
    ):
        self.knowledge_service = knowledge_service
        self.task_service = task_service

    async def submit(
        self,
        *,
        user_id: uuid.UUID,
        upload_file: UploadFile,
        kb_id: uuid.UUID | None = None,
    ) -> KnowledgeUploadResponse:
        """统一上传入口。

        Args:
            user_id: 当前用户 ID。
            upload_file: FastAPI 上传文件对象。
            kb_id: 目标知识库 ID；为 ``None`` 时自动使用/创建默认知识库。
        """
        use_default_kb = kb_id is None

        with trace_span(
            "knowledge.upload.save_file",
            {
                "user.id": user_id,
                "file.name": getattr(upload_file, "filename", None),
                "knowledge.upload.default_kb": use_default_kb,
            },
        ) as span:
            async with self.knowledge_service.uow:
                if use_default_kb:
                    kb = await self.knowledge_service.get_or_create_default_kb(
                        user_id=user_id,
                    )
                    kb_id = kb.id
                assert kb_id is not None

                file_obj = await self.knowledge_service.save_upload_file(
                    kb_id=kb_id,
                    user_id=user_id,
                    upload_file=upload_file,
                )
            set_span_attributes(
                span,
                {
                    "rag.kb_id": kb_id,
                    "rag.file_id": file_obj.id,
                    "file.size": getattr(file_obj, "file_size", None),
                },
            )

        return await self._create_and_dispatch_ingestion(
            kb_id=kb_id,
            user_id=user_id,
            file_obj=file_obj,
        )

    # ------------------------------------------------------------------
    # 内部：创建任务 → 投递异步消息
    # ------------------------------------------------------------------

    async def _create_and_dispatch_ingestion(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        file_obj: File,
    ) -> KnowledgeUploadResponse:
        try:
            with trace_span(
                "knowledge.upload.create_task",
                {
                    "rag.kb_id": kb_id,
                    "rag.file_id": file_obj.id,
                    "user.id": user_id,
                    "file.name": file_obj.filename,
                },
            ) as span:
                async with self.task_service.uow:
                    task = await self.task_service.create_kb_ingestion_task(
                        kb_id=kb_id,
                        file_id=file_obj.id,
                        file_path=file_obj.file_path,
                        filename=file_obj.filename,
                        user_id=user_id,
                    )
                set_span_attributes(
                    span, {"task.id": task.id, "task.status": task.status}
                )
        except AppException as exc:
            await self._handle_ingestion_failure(
                kb_id=kb_id, file_id=file_obj.id, exc=exc,
            )
            raise
        except Exception as exc:
            await self._handle_ingestion_failure(
                kb_id=kb_id, file_id=file_obj.id, exc=exc,
            )
            raise app_service_error(
                "创建知识处理任务失败，请稍后重试",
                code="KNOWLEDGE_TASK_CREATE_FAILED",
            ) from exc

        try:
            with trace_span(
                "knowledge.upload.dispatch_task",
                {
                    "rag.kb_id": kb_id,
                    "rag.file_id": file_obj.id,
                    "task.id": task.id,
                },
            ):
                await ingest_knowledge_file_task.kiq(
                    str(file_obj.id),
                    str(task.id),
                    inject_trace_context(),
                )
        except AppException as exc:
            await self._handle_ingestion_failure(
                kb_id=kb_id, file_id=file_obj.id, task_id=task.id, exc=exc,
            )
            raise
        except Exception as exc:
            await self._handle_ingestion_failure(
                kb_id=kb_id, file_id=file_obj.id, task_id=task.id, exc=exc,
            )
            raise app_dependency_unavailable(
                "任务投递失败，请稍后重试",
                code="KNOWLEDGE_TASK_DISPATCH_FAILED",
            ) from exc

        return KnowledgeUploadResponse(
            task_id=task.id,
            file_id=file_obj.id,
            kb_id=kb_id,
            file_status=file_obj.status,
            task_status=task.status,
        )

    # ------------------------------------------------------------------
    # 统一错误处理
    # ------------------------------------------------------------------

    async def _handle_ingestion_failure(
        self,
        *,
        kb_id: uuid.UUID,
        file_id: uuid.UUID,
        exc: Exception,
        task_id: uuid.UUID | None = None,
    ) -> None:
        """处理任务创建或投递阶段的失败，确保状态一致性。"""
        # 标记 task 失败（仅在 task 已创建的投递阶段）
        if task_id is not None:
            try:
                async with self.task_service.uow:
                    await self.task_service.mark_failed(
                        task_id=task_id,
                        error_log=f"任务投递失败: {exc}",
                    )
            except Exception:
                logger.exception("任务失败状态更新异常: task_id=%s", task_id)

        # 标记文件失败
        try:
            async with self.knowledge_service.uow:
                await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.FAILED,
                )
        except Exception:
            logger.exception("文件失败状态更新异常: file_id=%s", file_id)

        # 统一日志
        if isinstance(exc, AppException):
            logger.warning(
                "知识库任务失败: kb_id=%s, file_id=%s, task_id=%s, error=%s",
                kb_id, file_id, task_id, exc,
            )
        else:
            logger.exception(
                "知识库任务失败: kb_id=%s, file_id=%s, task_id=%s",
                kb_id, file_id, task_id,
            )
