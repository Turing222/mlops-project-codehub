import asyncio
import uuid
from pathlib import Path

import pypdfium2 as pdfium

from backend.core.exceptions import (
    AppError,
    ResourceNotFound,
    ServiceError,
    ValidationError,
)
from backend.core.trace_utils import set_span_attributes, trace_span
from backend.models.orm.knowledge import FileStatus
from backend.services.chunking_service import ChunkingService
from backend.services.knowledge_service import KnowledgeService
from backend.services.vector_index_service import VectorIndexService

TEXT_FILE_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".log",
    ".py",
    ".sql",
}

PDF_FILE_SUFFIXES = {".pdf"}


class KnowledgeRAGWorkflow:
    def __init__(
        self,
        knowledge_service: KnowledgeService,
        chunking_service: ChunkingService,
        vector_index_service: VectorIndexService,
    ):
        self.knowledge_service = knowledge_service
        self.chunking_service = chunking_service
        self.vector_index_service = vector_index_service

    async def ingest_file(
        self,
        *,
        file_id: uuid.UUID,
    ) -> None:
        with trace_span("knowledge.ingest.load_file", {"rag.file_id": file_id}) as span:
            async with self.knowledge_service.uow:
                file_obj = await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.PARSING,
                )
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
            raise ResourceNotFound("文件不存在")

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
                    set_span_attributes(span, {"rag.chunk_count": len(chunks)})
            if not chunks:
                raise ValidationError("文件无可用文本内容，无法构建 RAG 索引")

            with trace_span(
                "knowledge.ingest.index_chunks",
                {
                    "rag.file_id": file_id,
                    "rag.kb_id": file_obj.kb_id,
                    "rag.chunk_count": len(chunks),
                },
            ):
                async with self.knowledge_service.uow:
                    await self.knowledge_service.set_file_status(
                        file_id=file_id,
                        status=FileStatus.CHUNKING,
                    )
                async with self.vector_index_service.uow:
                    await self.vector_index_service.replace_file_chunks(
                        file_id=file_id,
                        chunks=chunks,
                        filename=file_obj.filename,
                        file_path=file_obj.file_path,
                    )
                async with self.knowledge_service.uow:
                    await self.knowledge_service.set_file_status(
                        file_id=file_id,
                        status=FileStatus.READY,
                    )
        except FileNotFoundError as exc:
            async with self.knowledge_service.uow:
                await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.FAILED,
                )
            raise ResourceNotFound("上传文件在存储路径中不存在") from exc
        except AppError:
            async with self.knowledge_service.uow:
                await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.FAILED,
                )
            raise
        except Exception as exc:
            async with self.knowledge_service.uow:
                await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.FAILED,
                )
            raise ServiceError("知识文件处理失败，请稍后重试") from exc

    def _extract_chunks(self, file_path: Path) -> list[str]:
        suffix = file_path.suffix.lower()
        if suffix in TEXT_FILE_SUFFIXES:
            return self._extract_text_chunks(file_path)
        if suffix in PDF_FILE_SUFFIXES:
            return self._extract_pdf_chunks(file_path)

        raise ValidationError(
            f"暂不支持的文件类型: {suffix or '(无扩展名)'}，建议使用 txt/md/pdf"
        )

    def _extract_text_chunks(self, file_path: Path) -> list[str]:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return self.chunking_service.split_text(text)

    def _extract_pdf_chunks(self, file_path: Path) -> list[str]:
        try:
            text = self._extract_pdf_text(file_path)
            return self.chunking_service.split_text(text)
        except AppError:
            raise
        except Exception as exc:
            raise ValidationError(f"文件解析失败: {file_path.name}") from exc

    @staticmethod
    def _extract_pdf_text(file_path: Path) -> str:
        page_texts: list[str] = []
        with pdfium.PdfDocument(file_path) as document:
            for page_index in range(len(document)):
                page = document[page_index]
                text_page = None
                try:
                    text_page = page.get_textpage()
                    text = text_page.get_text_range().strip()
                    if text:
                        page_texts.append(text)
                finally:
                    if text_page is not None:
                        text_page.close()
                    page.close()
        return "\n\n".join(page_texts)
