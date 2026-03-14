import logging
import uuid

from backend.core.exceptions import AppError
from backend.domain.interfaces import (
    AbstractRAGEmbedder,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.models.orm.chunk import DocumentChunk
from backend.services.vector_index_service import VectorIndexService

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
        self.vector_index_service = VectorIndexService(uow=uow, embedder=embedder)
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
            hits = await self.vector_index_service.search_chunks_for_kb(
                query_text=query_text,
                kb_id=kb_id,
                limit=limit,
            )
        except AppError:
            raise
        except Exception as exc:
            logger.warning("RAG 检索失败，降级为无检索上下文: %s", exc)
            return []

        return self._format_hits(hits)

    async def retrieve_fulltext(
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
            hits = await self.vector_index_service.search_chunks_for_kb_fulltext(
                query_text=query_text,
                kb_id=kb_id,
                limit=limit,
            )
        except AppError:
            raise
        except Exception as exc:
            logger.warning("RAG 全文检索失败，降级为无检索上下文: %s", exc)
            return []

        return self._format_hits(hits)

    async def retrieve_hybrid(
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
            hits = await self.vector_index_service.search_chunks_for_kb_hybrid(
                query_text=query_text,
                kb_id=kb_id,
                limit=limit,
            )
        except AppError:
            raise
        except Exception as exc:
            logger.warning("RAG 混合检索失败，降级为无检索上下文: %s", exc)
            return []

        return self._format_hits(hits)

    @staticmethod
    def _format_hits(hits: list[tuple[DocumentChunk, float]]) -> list[dict]:
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
