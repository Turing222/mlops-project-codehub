"""Knowledge RAG ingestion workflow.

职责：下载已上传文件、解析文本、切片并替换向量索引。
边界：本模块不保存上传文件、不创建任务；上传和任务投递由 KnowledgeUploadWorkflow 负责。
失败处理：解析或索引失败会把文件状态标记为 FAILED。
"""

import asyncio
import logging
import uuid
from collections.abc import Collection
from pathlib import Path
from typing import cast

from backend.core.constants import SUPPORTED_KNOWLEDGE_SUFFIXES
from backend.core.exceptions import (
    AppException,
    app_not_found,
    app_service_error,
    app_validation_error,
)
from backend.models.orm.knowledge import FileStatus
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.chunking_service import ChunkingService, ChunkPayload
from backend.services.knowledge_service import KnowledgeService
from backend.services.safety_scanner import SafetyScanner
from backend.services.task_service import TaskService
from backend.services.vector_index_service import VectorIndexService

logger = logging.getLogger(__name__)


class KnowledgeRAGWorkflow:
    """知识文件入库编排器。"""

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        chunking_service: ChunkingService,
        vector_index_service: VectorIndexService,
        task_service: TaskService | None = None,
    ) -> None:
        self.knowledge_service = knowledge_service
        self.chunking_service = chunking_service
        self.vector_index_service = vector_index_service
        self.task_service = task_service

    async def ingest_file(
        self,
        *,
        file_id: uuid.UUID,
        task_id: uuid.UUID | None = None,
        expected_attempt: int | None = None,
    ) -> None:
        with trace_span("knowledge.ingest.load_file", {"rag.file_id": file_id}) as span:
            async with self.knowledge_service.uow:
                await self._ensure_active_attempt(
                    task_id=task_id,
                    expected_attempt=expected_attempt,
                )
                success = await self.knowledge_service.try_transition_file_status(
                    file_id=file_id,
                    expected_previous_statuses=[FileStatus.UPLOADED],
                    target_status=FileStatus.PARSING,
                )
                if not success:
                    file_obj = await self.knowledge_service.get_file(file_id)
                    if not file_obj:
                        raise app_not_found(
                            "文件不存在", code="KNOWLEDGE_FILE_NOT_FOUND"
                        )
                    raise app_validation_error(
                        "文件状态不为 UPLOADED 或已被并发任务处理",
                        code="KNOWLEDGE_FILE_ALREADY_INGESTING",
                    )
                file_obj = await self.knowledge_service.get_file(file_id)
            if file_obj:
                set_span_attributes(
                    span,
                    {
                        "rag.kb_id": file_obj.kb_id,
                        "file.name": file_obj.filename,
                        "file.path": file_obj.file_path,
                        "file.storage_backend": file_obj.storage_backend,
                        "file.storage_key": file_obj.storage_key,
                        "file.size": file_obj.file_size,
                    },
                )
        if not file_obj:
            raise app_not_found("文件不存在", code="KNOWLEDGE_FILE_NOT_FOUND")

        try:
            async with self.knowledge_service.storage.download_to_temp(
                file_obj
            ) as file_path:
                with trace_span(
                    "knowledge.ingest.extract_chunks",
                    {
                        "rag.file_id": file_id,
                        "rag.kb_id": file_obj.kb_id,
                        "file.name": file_obj.filename,
                        "file.extension": file_path.suffix.lower(),
                        "file.storage_backend": file_obj.storage_backend,
                    },
                ) as span:
                    chunks = await asyncio.to_thread(self._extract_chunks, file_path)
                    chunks = self._prepare_chunks_for_index(
                        chunks=chunks,
                        filename=file_obj.filename,
                        file_path=file_obj.file_path,
                    )
                    set_span_attributes(span, {"rag.chunk_count": len(chunks)})
            if not chunks:
                raise app_validation_error(
                    "文件无可用文本内容，无法构建 RAG 索引",
                    code="KNOWLEDGE_FILE_NO_TEXT",
                )

            with trace_span(
                "knowledge.ingest.index_chunks",
                {
                    "rag.file_id": file_id,
                    "rag.kb_id": file_obj.kb_id,
                    "rag.chunk_count": len(chunks),
                },
            ):
                async with self.knowledge_service.uow:
                    await self._ensure_active_attempt(
                        task_id=task_id,
                        expected_attempt=expected_attempt,
                    )
                    success = await self.knowledge_service.try_transition_file_status(
                        file_id=file_id,
                        expected_previous_statuses=[FileStatus.PARSING],
                        target_status=FileStatus.CHUNKING,
                    )
                    if not success:
                        raise app_validation_error(
                            "文件状态不为 PARSING 无法进入 CHUNKING 状态",
                            code="KNOWLEDGE_FILE_NOT_PARSING",
                        )
                    await self.vector_index_service.replace_file_chunks(
                        file_id=file_id,
                        chunks=chunks,
                        filename=file_obj.filename,
                        file_path=file_obj.file_path,
                    )
                    success = await self.knowledge_service.try_transition_file_status(
                        file_id=file_id,
                        expected_previous_statuses=[FileStatus.CHUNKING],
                        target_status=FileStatus.READY,
                    )
                    if not success:
                        raise app_validation_error(
                            "文件状态不为 CHUNKING 无法进入 READY 状态",
                            code="KNOWLEDGE_FILE_NOT_CHUNKING",
                        )
        except FileNotFoundError as exc:
            await self._cleanup_failed_ingestion(
                file_id=file_id,
                task_id=task_id,
                expected_attempt=expected_attempt,
            )
            raise app_not_found(
                "上传文件在存储路径中不存在",
                code="KNOWLEDGE_FILE_OBJECT_NOT_FOUND",
            ) from exc
        except AppException:
            await self._cleanup_failed_ingestion(
                file_id=file_id,
                task_id=task_id,
                expected_attempt=expected_attempt,
            )
            raise
        except Exception as exc:
            await self._cleanup_failed_ingestion(
                file_id=file_id,
                task_id=task_id,
                expected_attempt=expected_attempt,
            )
            raise app_service_error(
                "知识文件处理失败，请稍后重试",
                code="KNOWLEDGE_FILE_INGEST_FAILED",
            ) from exc

    async def _cleanup_failed_ingestion(
        self,
        *,
        file_id: uuid.UUID,
        task_id: uuid.UUID | None = None,
        expected_attempt: int | None = None,
    ) -> None:
        expected_statuses: Collection[FileStatus] = (
            FileStatus.UPLOADED,
            FileStatus.PARSING,
            FileStatus.CHUNKING,
            FileStatus.READY,
        )
        async with self.knowledge_service.uow:
            if not await self._attempt_is_active(
                task_id=task_id,
                expected_attempt=expected_attempt,
            ):
                logger.warning(
                    "Skipped stale Knowledge worker cleanup",
                    extra={
                        "event": "knowledge_ingestion_stale_cleanup_rejected",
                        "file_id": str(file_id),
                        "task_id": str(task_id) if task_id else None,
                        "attempt": expected_attempt,
                    },
                )
                return
            await self.knowledge_service.delete_chunks_for_file(file_id=file_id)
            success = await self.knowledge_service.try_transition_file_status(
                file_id=file_id,
                expected_previous_statuses=expected_statuses,
                target_status=FileStatus.FAILED,
            )
        if not success:
            logger.warning(
                "Failed to mark knowledge file ingestion as failed: file_id=%s",
                file_id,
            )

    async def _ensure_active_attempt(
        self,
        *,
        task_id: uuid.UUID | None,
        expected_attempt: int | None,
    ) -> None:
        if not await self._attempt_is_active(
            task_id=task_id,
            expected_attempt=expected_attempt,
        ):
            raise app_validation_error(
                "知识入库任务租约已失效",
                code="KNOWLEDGE_TASK_LEASE_LOST",
            )

    async def _attempt_is_active(
        self,
        *,
        task_id: uuid.UUID | None,
        expected_attempt: int | None,
    ) -> bool:
        if task_id is None and expected_attempt is None:
            return True
        if task_id is None or expected_attempt is None or self.task_service is None:
            return False
        return await self.task_service.heartbeat_kb_ingestion(
            task_id=task_id,
            expected_attempt=expected_attempt,
        )

    def _extract_chunks(self, file_path: Path) -> list[ChunkPayload]:
        suffix = file_path.suffix.lower()
        if suffix in SUPPORTED_KNOWLEDGE_SUFFIXES:
            return self._extract_markdown_chunks(file_path)

        raise app_validation_error(
            "当前仅支持 Markdown 文件",
            code="KNOWLEDGE_FILE_UNSUPPORTED_TYPE",
            details={
                "suffix": suffix or "(无扩展名)",
                "supported_suffixes": sorted(SUPPORTED_KNOWLEDGE_SUFFIXES),
            },
        )

    def _extract_markdown_chunks(self, file_path: Path) -> list[ChunkPayload]:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return self.chunking_service.split_text(text, file_suffix=file_path.suffix)

    @staticmethod
    def _prepare_chunks_for_index(
        *,
        chunks: list[ChunkPayload],
        filename: str,
        file_path: str,
    ) -> list[ChunkPayload]:
        prepared_chunks: list[ChunkPayload] = []
        for chunk in chunks:
            content = chunk["content"]
            meta_info = {
                **(chunk.get("meta_info") or {}),
                "filename": filename,
                "path": file_path,
                "source_path": file_path,
            }
            section_path = chunk.get("section_path")
            page_label = chunk.get("page_label")
            if section_path:
                meta_info["section_path"] = section_path
            if page_label:
                meta_info["page_label"] = page_label

            scan_result = SafetyScanner.scan(content)
            meta_info["injection_risk"] = scan_result.injection_risk
            meta_info["sensitive_data_risk"] = scan_result.sensitive_data_risk

            prepared = dict(chunk)
            prepared["content"] = content
            prepared["meta_info"] = meta_info
            prepared["embedding_content"] = "\n".join(
                [
                    KnowledgeRAGWorkflow._build_context_prefix(
                        filename=filename,
                        section_path=section_path,
                        page_label=page_label,
                    ),
                    content,
                ]
            ).strip()
            prepared_chunks.append(cast(ChunkPayload, prepared))
        return prepared_chunks

    @staticmethod
    def _build_context_prefix(
        *,
        filename: str,
        section_path: str | None = None,
        page_label: str | None = None,
    ) -> str:
        parts = [f"[文档: {filename}]"]
        if section_path:
            parts.append(f"[章节: {section_path}]")
        if page_label:
            parts.append(f"[页码: {page_label}]")
        return " ".join(parts)
