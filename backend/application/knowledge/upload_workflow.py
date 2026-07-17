"""Knowledge upload and durable ingestion submission workflow.

职责：在一个 UoW 中持久化 File、TaskJob 与 TaskOutbox，并在 commit 后快速发布。
边界：本模块不解析文件；broker 失败只保留待重试 outbox，不回写伪失败终态。
失败处理：数据库事务回滚后尽力删除本次新写的对象，避免孤儿存储对象。
"""

from __future__ import annotations

import logging
import uuid

from backend.application.knowledge.outbox_relay import KnowledgeOutboxRelayService
from backend.contracts.interfaces import AbstractTaskDispatcher
from backend.contracts.uploads import UploadFileLike
from backend.models.orm.knowledge import File
from backend.models.schemas.knowledge_schema import KnowledgeUploadResponse
from backend.observability.trace_utils import (
    inject_trace_context,
    set_span_attributes,
    trace_span,
)
from backend.services.knowledge_service import KnowledgeService, SavedKnowledgeFile
from backend.services.task_service import TaskService

logger = logging.getLogger(__name__)


class KnowledgeUploadWorkflow:
    """Persist an accepted ingestion before treating broker delivery as best effort."""

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        task_service: TaskService,
        dispatcher: AbstractTaskDispatcher,
    ) -> None:
        if knowledge_service.uow is not task_service.uow:
            raise ValueError("Knowledge upload services must share one UnitOfWork")
        self.knowledge_service = knowledge_service
        self.task_service = task_service
        self.dispatcher = dispatcher
        self.uow = knowledge_service.uow

    async def submit(
        self,
        *,
        user_id: uuid.UUID,
        upload_file: UploadFileLike,
        kb_id: uuid.UUID | None = None,
    ) -> KnowledgeUploadResponse:
        """Atomically persist accepted work, then attempt a non-fatal fast publish."""
        use_default_kb = kb_id is None
        save_result: SavedKnowledgeFile | None = None
        file_obj: File | None = None
        outbox_id: uuid.UUID | None = None
        transaction_body_completed = False

        try:
            with trace_span(
                "knowledge.upload.persist",
                {
                    "user.id": user_id,
                    "file.name": getattr(upload_file, "filename", None),
                    "knowledge.upload.default_kb": use_default_kb,
                },
            ) as span:
                async with self.uow:
                    if use_default_kb:
                        kb = await self.knowledge_service.get_or_create_default_kb(
                            user_id=user_id,
                        )
                        kb_id = kb.id
                    assert kb_id is not None

                    save_result = (
                        await self.knowledge_service.save_upload_file_for_ingestion(
                            kb_id=kb_id,
                            user_id=user_id,
                            upload_file=upload_file,
                        )
                    )
                    file_obj = save_result.file
                    if save_result.should_ingest:
                        task = await self.task_service.create_kb_ingestion_task(
                            kb_id=kb_id,
                            file_id=file_obj.id,
                            file_path=file_obj.file_path,
                            filename=file_obj.filename,
                            user_id=user_id,
                        )
                        outbox = await self.task_service.create_kb_ingestion_outbox(
                            task_id=task.id,
                            file_id=file_obj.id,
                            trace_context=inject_trace_context(),
                        )
                        outbox_id = outbox.id
                    else:
                        task = (
                            await self.task_service.create_completed_kb_ingestion_task(
                                kb_id=kb_id,
                                file_id=file_obj.id,
                                file_path=file_obj.file_path,
                                filename=file_obj.filename,
                                user_id=user_id,
                                deduplicated=save_result.deduplicated,
                            )
                        )
                    transaction_body_completed = True
                set_span_attributes(
                    span,
                    {
                        "rag.kb_id": kb_id,
                        "rag.file_id": file_obj.id,
                        "task.id": task.id,
                        "task.status": task.status,
                        "task.outbox_id": outbox_id,
                        "file.size": getattr(file_obj, "file_size", None),
                        "knowledge.upload.deduplicated": save_result.deduplicated,
                    },
                )
        except Exception:
            if (
                save_result is not None
                and save_result.should_ingest
                and not transaction_body_completed
            ):
                await self._discard_rolled_back_object(save_result.file)
            elif save_result is not None and save_result.should_ingest:
                # A connection loss while COMMIT is in flight has an uncertain
                # outcome. Preserve the object so a possibly committed File does
                # not point at deleted bytes; orphan reconciliation can clean up
                # a definitively unreferenced object later.
                logger.error(
                    "Knowledge upload commit outcome is uncertain",
                    extra={
                        "event": "knowledge_upload_commit_outcome_uncertain",
                        "file_id": str(save_result.file.id),
                    },
                )
            raise

        assert kb_id is not None
        assert file_obj is not None
        if outbox_id is not None:
            with trace_span(
                "knowledge.upload.fast_publish",
                {
                    "rag.kb_id": kb_id,
                    "rag.file_id": file_obj.id,
                    "task.id": task.id,
                    "task.outbox_id": outbox_id,
                },
            ):
                try:
                    await KnowledgeOutboxRelayService(
                        uow=self.uow,
                        dispatcher=self.dispatcher,
                    ).publish_one(outbox_id=outbox_id)
                except Exception:
                    logger.exception(
                        "Knowledge outbox fast publish failed after commit",
                        extra={
                            "event": "knowledge_outbox_fast_publish_failed",
                            "file_id": str(file_obj.id),
                            "task_id": str(task.id),
                            "outbox_id": str(outbox_id),
                        },
                    )

        return KnowledgeUploadResponse(
            task_id=task.id,
            file_id=file_obj.id,
            kb_id=kb_id,
            file_status=file_obj.status,
            task_status=task.status,
            deduplicated=save_result.deduplicated,
        )

    async def _discard_rolled_back_object(self, file_obj: File) -> None:
        try:
            await self.knowledge_service.delete_stored_object(file_obj=file_obj)
        except Exception:
            logger.exception(
                "Rolled-back Knowledge upload object cleanup failed",
                extra={
                    "event": "knowledge_upload_rollback_object_cleanup_failed",
                    "file_id": str(file_obj.id),
                },
            )
