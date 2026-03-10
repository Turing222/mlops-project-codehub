import asyncio
import uuid
from pathlib import Path

from backend.core.exceptions import ResourceNotFound, ValidationError
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
        file_obj = await self.knowledge_service.set_file_status(
            file_id=file_id,
            status=FileStatus.PARSING,
        )
        if not file_obj:
            raise ResourceNotFound("文件不存在")

        file_path = Path(file_obj.file_path)
        if not file_path.exists():
            await self.knowledge_service.set_file_status(
                file_id=file_id,
                status=FileStatus.FAILED,
            )
            raise ResourceNotFound("上传文件在存储路径中不存在")

        try:
            text = await asyncio.to_thread(self._extract_text, file_path)
            chunks = self.chunking_service.split_text(text)
            if not chunks:
                raise ValidationError("文件无可用文本内容，无法构建 RAG 索引")

            await self.knowledge_service.set_file_status(
                file_id=file_id,
                status=FileStatus.CHUNKING,
            )
            await self.vector_index_service.replace_file_chunks(
                file_id=file_id,
                chunks=chunks,
                filename=file_obj.filename,
                file_path=str(file_path),
            )

            await self.knowledge_service.set_file_status(
                file_id=file_id,
                status=FileStatus.READY,
            )
        except Exception:
            await self.knowledge_service.set_file_status(
                file_id=file_id,
                status=FileStatus.FAILED,
            )
            raise

    def _extract_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix in TEXT_FILE_SUFFIXES:
            return file_path.read_text(encoding="utf-8", errors="ignore")
        if suffix in {".pdf", ".docx", ".pptx"}:
            try:
                from docling.document_converter import DocumentConverter

                converter = DocumentConverter()
                result = converter.convert(str(file_path))
                if hasattr(result.document, "export_to_markdown"):
                    return result.document.export_to_markdown()
                if hasattr(result.document, "export_to_text"):
                    return result.document.export_to_text()
            except Exception as exc:
                raise ValidationError(f"文件解析失败: {file_path.name}") from exc

        raise ValidationError(
            f"暂不支持的文件类型: {suffix or '(无扩展名)'}，建议使用 txt/md/pdf/docx"
        )
