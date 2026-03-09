import asyncio
import logging
import uuid

from backend.domain.interfaces import (
    AbstractRAGEmbedder,
    AbstractRAGService,
    AbstractUnitOfWork,
)

logger = logging.getLogger(__name__)


class RAGService(AbstractRAGService):
    """
    本地 RAG 检索服务（服务层）。
    - 负责 query embedding
    - 负责按 kb_id 做向量检索
    - 返回统一结构，供 Workflow 组装 Prompt 与回写 search_context
    """

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        embedder: AbstractRAGEmbedder,
        top_k: int = 4,
    ):
        self.uow = uow
        self.embedder = embedder
        self.top_k = top_k

    async def retrieve(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
    ) -> list[dict]:
        if kb_id is None or not query_text.strip():
            return []

        limit = top_k or self.top_k
        if limit <= 0:
            return []

        try:
            query_vector = await asyncio.to_thread(self.embedder.encode_query, query_text)
        except Exception as exc:
            logger.warning("RAG embedding 失败，降级为无检索上下文: %s", exc)
            return []

        async with self.uow:
            hits = await self.uow.knowledge.search_chunks_for_kb(
                query_vector=query_vector,
                kb_id=kb_id,
                limit=limit,
            )

        chunks: list[dict] = []
        for chunk, distance in hits:
            chunks.append(
                {
                    "id": str(chunk.id),
                    "content": chunk.content,
                    "source_type": str(chunk.source_type),
                    "file_id": str(chunk.file_id) if chunk.file_id else None,
                    "message_id": str(chunk.message_id) if chunk.message_id else None,
                    "distance": distance,
                    "score": max(0.0, 1.0 - distance),
                }
            )
        return chunks
