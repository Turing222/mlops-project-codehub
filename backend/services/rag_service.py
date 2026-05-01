"""RAG retrieval service.

职责：对知识库执行向量、全文或混合检索，并返回 Prompt 可消费的片段结构。
边界：本模块不解析文件、不维护索引；索引写入由 VectorIndexService 完成。
失败处理：非业务异常降级为空检索上下文，保证聊天主链路可继续。
"""

import logging
import uuid

from backend.core.exceptions import AppException
from backend.core.trace_utils import set_span_attributes, trace_span
from backend.domain.interfaces import (
    AbstractRAGEmbedder,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.models.orm.chunk import DocumentChunk
from backend.services.vector_index_service import VectorIndexService

logger = logging.getLogger(__name__)


class RAGService(AbstractRAGService):
    """知识库检索服务。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        embedder: AbstractRAGEmbedder,
        top_k: int = 4,
    ) -> None:
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
            with trace_span(
                "rag.retrieve.vector",
                {
                    "rag.kb_id": kb_id,
                    "rag.top_k": limit,
                    "rag.query.char_count": len(query_text),
                },
            ) as span:
                hits = await self.vector_index_service.search_chunks_for_kb(
                    query_text=query_text,
                    kb_id=kb_id,
                    limit=limit,
                )
                set_span_attributes(span, {"rag.hit_count": len(hits)})
        except AppException:
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
            with trace_span(
                "rag.retrieve.fulltext",
                {
                    "rag.kb_id": kb_id,
                    "rag.top_k": limit,
                    "rag.query.char_count": len(query_text),
                },
            ) as span:
                hits = await self.vector_index_service.search_chunks_for_kb_fulltext(
                    query_text=query_text,
                    kb_id=kb_id,
                    limit=limit,
                )
                set_span_attributes(span, {"rag.hit_count": len(hits)})
        except AppException:
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
            with trace_span(
                "rag.retrieve.hybrid",
                {
                    "rag.kb_id": kb_id,
                    "rag.top_k": limit,
                    "rag.query.char_count": len(query_text),
                },
            ) as span:
                hits = await self.vector_index_service.search_chunks_for_kb_hybrid(
                    query_text=query_text,
                    kb_id=kb_id,
                    limit=limit,
                )
                set_span_attributes(span, {"rag.hit_count": len(hits)})
        except AppException:
            raise
        except Exception as exc:
            logger.warning("RAG 混合检索失败，降级为无检索上下文: %s", exc)
            return []

        return self._format_hits(hits)

    @staticmethod
    def _format_hits(hits: list[tuple[DocumentChunk, float]]) -> list[dict]:
        chunks: list[dict] = []
        for chunk, distance in hits:
            file_obj = getattr(chunk, "__dict__", {}).get("file")
            chunks.append(
                {
                    "id": str(chunk.id),
                    "content": chunk.content,
                    "source_type": str(chunk.source_type),
                    "file_id": str(chunk.file_id) if chunk.file_id else None,
                    "message_id": str(chunk.message_id) if chunk.message_id else None,
                    "filename": getattr(file_obj, "filename", None)
                    if file_obj is not None
                    else None,
                    "chunk_index": chunk.chunk_index,
                    "meta_info": chunk.meta_info or {},
                    "distance": distance,
                    "score": max(0.0, 1.0 - distance),
                }
            )
        return chunks
