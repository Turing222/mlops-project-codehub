import asyncio
import uuid

from backend.domain.interfaces import AbstractRAGEmbedder, AbstractUnitOfWork
from backend.models.orm.chunk import ChunkSourceType, DocumentChunk
from backend.services.base import BaseService


class VectorIndexService(BaseService[AbstractUnitOfWork]):
    def __init__(
        self,
        uow: AbstractUnitOfWork,
        embedder: AbstractRAGEmbedder,
    ):
        super().__init__(uow)
        self.embedder = embedder

    async def replace_file_chunks(
        self,
        *,
        file_id: uuid.UUID,
        chunks: list[str],
        filename: str,
        file_path: str,
    ) -> None:
        chunk_records: list[dict] = []
        for idx, chunk_text in enumerate(chunks):
            embedding = await asyncio.to_thread(self.embedder.encode_query, chunk_text)
            chunk_records.append(
                {
                    "source_type": ChunkSourceType.FILE,
                    "file_id": file_id,
                    "content": chunk_text,
                    "token_count": len(chunk_text),
                    "chunk_index": idx,
                    "meta_info": {
                        "filename": filename,
                        "path": file_path,
                    },
                    "embedding": embedding,
                }
            )

        async with self.uow:
            await self.uow.knowledge.delete_chunks_for_file(file_id=file_id)
            await self.uow.knowledge.add_chunks(chunk_records)

    async def search_chunks_for_kb(
        self,
        *,
        query_text: str,
        kb_id: uuid.UUID,
        limit: int,
    ) -> list[tuple[DocumentChunk, float]]:
        if not query_text.strip() or limit <= 0:
            return []

        query_vector = await asyncio.to_thread(self.embedder.encode_query, query_text)
        async with self.uow:
            return await self.uow.knowledge.search_chunks_for_kb(
                query_vector=query_vector,
                kb_id=kb_id,
                limit=limit,
            )
