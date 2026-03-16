import asyncio
import uuid
from pathlib import Path

from backend.core.docling_models import DoclingModelFactory
from backend.core.exceptions import (
    AppError,
    ResourceNotFound,
    ServiceError,
    ValidationError,
)
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

DOCLING_STRUCTURED_SUFFIXES = {".pdf", ".docx", ".pptx"}


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
        async with self.knowledge_service.uow:
            file_obj = await self.knowledge_service.set_file_status(
                file_id=file_id,
                status=FileStatus.PARSING,
            )
        if not file_obj:
            raise ResourceNotFound("文件不存在")

        file_path = Path(file_obj.file_path)
        if not file_path.exists():
            async with self.knowledge_service.uow:
                await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.FAILED,
                )
            raise ResourceNotFound("上传文件在存储路径中不存在")

        try:
            chunks = await asyncio.to_thread(self._extract_chunks, file_path)
            if not chunks:
                raise ValidationError("文件无可用文本内容，无法构建 RAG 索引")

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
                    file_path=str(file_path),
                )
            async with self.knowledge_service.uow:
                await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.READY,
                )
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
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            return self.chunking_service.split_text(text)
        if suffix in DOCLING_STRUCTURED_SUFFIXES:
            return self._extract_docling_chunks(file_path)

        raise ValidationError(
            f"暂不支持的文件类型: {suffix or '(无扩展名)'}，建议使用 txt/md/pdf/docx"
        )

    def _extract_docling_chunks(self, file_path: Path) -> list[str]:
        try:
            converter = DoclingModelFactory.get_converter()
            chunker = DoclingModelFactory.get_hierarchical_chunker()

            result = converter.convert(str(file_path))
            chunks: list[str] = []

            for chunk in chunker.chunk(dl_doc=result.document):
                text = chunker.contextualize(chunk).strip()
                if not text:
                    continue

                # 对超长结构块做二次切分，避免向量块过大
                if len(text) > self.chunking_service.chunk_size:
                    chunks.extend(self.chunking_service.split_text(text))
                else:
                    chunks.append(text)

            if chunks:
                return chunks

            fallback_text = self._export_docling_document(result.document)
            return self.chunking_service.split_text(fallback_text)
        except AppError:
            raise
        except Exception as exc:
            raise ValidationError(f"文件解析失败: {file_path.name}") from exc

    @staticmethod
    def _export_docling_document(document: object) -> str:
        if hasattr(document, "export_to_markdown"):
            return document.export_to_markdown()
        if hasattr(document, "export_to_text"):
            return document.export_to_text()
        return ""
