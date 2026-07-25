"""RAG retrieval service.

职责：对知识库执行向量、全文或混合检索，并返回 Prompt 可消费的片段结构。
边界：本模块不解析文件、不维护索引；索引写入由 VectorIndexService 完成。
失败处理：非业务异常降级为空检索上下文，保证聊天主链路可继续。
"""

import logging
import uuid
from collections.abc import Sequence
from typing import Any, cast

from backend.contracts.interfaces import (
    AbstractRAGEmbedder,
    AbstractRAGService,
    AbstractRerankService,
)
from backend.core.exceptions import AppException
from backend.models.orm.chunk import DocumentChunk
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.vector_index_service import RetrievalHit, VectorIndexService

logger = logging.getLogger(__name__)


def select_rerank_fallback_candidates(
    candidates: list[dict],
    limit: int,
) -> list[dict]:
    """Keep candidate order while preserving a web hit when rerank is unavailable."""
    if limit <= 0:
        return []

    selected = list(candidates)[:limit]
    if not selected or any(chunk.get("source_type") == "web" for chunk in selected):
        return selected

    web_candidate = next(
        (chunk for chunk in candidates if chunk.get("source_type") == "web"),
        None,
    )
    if web_candidate is None:
        return selected

    selected[-1] = web_candidate
    return selected


class RAGService(AbstractRAGService):
    """知识库检索服务。"""

    def __init__(
        self,
        embedder: AbstractRAGEmbedder,
        vector_index_service: VectorIndexService,
        top_k: int = 4,
        reranker: AbstractRerankService | None = None,
        rerank_candidate_count: int = 20,
        rerank_top_k: int = 4,
        rerank_score_kind: str = "bifrost_rerank",
    ) -> None:
        self.embedder = embedder
        self.vector_index_service = vector_index_service
        self.top_k = top_k
        self.reranker = reranker
        self.rerank_candidate_count = rerank_candidate_count
        self.rerank_top_k = rerank_top_k
        self.rerank_score_kind = rerank_score_kind

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
            logger.warning(
                "RAG retrieval failed; using no retrieved context",
                extra={
                    "event": "rag_retrieval_degraded",
                    "error_type": type(exc).__name__,
                },
            )
            return []

        return self._format_hits(hits, default_retrieval_mode="vector")

    async def rerank(
        self,
        query_text: str,
        candidates: list[dict],
        top_k: int | None = None,
    ) -> list[dict]:
        limit = top_k or self.rerank_top_k
        if not candidates or limit <= 0:
            return list(candidates)[:limit] if limit > 0 else []

        if self.reranker is not None:
            try:
                rankings = await self.reranker.rerank(
                    query_text=query_text,
                    documents=[
                        str(candidate.get("content") or "") for candidate in candidates
                    ],
                    top_k=limit,
                )
                return self.apply_rankings(
                    candidates=candidates,
                    rankings=rankings,
                    limit=limit,
                    score_kind=self.rerank_score_kind,
                    index_base=0,
                )
            except Exception as exc:
                logger.warning(
                    "Native rerank failed; preserving candidate order",
                    extra={
                        "event": "rag_rerank_degraded",
                        "error_type": type(exc).__name__,
                    },
                )

        return select_rerank_fallback_candidates(candidates, limit)

    async def retrieve_with_rerank(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
        candidate_count: int | None = None,
    ) -> list[dict]:
        if kb_id is None or not query_text.strip():
            return []

        limit = top_k or self.rerank_top_k or self.top_k
        candidate_limit = candidate_count or self.rerank_candidate_count
        if limit <= 0 or candidate_limit <= 0:
            return []

        try:
            with trace_span(
                "rag.rerank.retrieve_candidates",
                {
                    "rag.kb_id": kb_id,
                    "rag.top_k": limit,
                    "rag.candidate_count": candidate_limit,
                    "rag.query.char_count": len(query_text),
                },
            ) as span:
                hits = await self.vector_index_service.search_chunks_for_kb_hybrid(
                    query_text=query_text,
                    kb_id=kb_id,
                    limit=candidate_limit,
                )
                candidates = self._format_hits(hits, default_retrieval_mode="hybrid")
                set_span_attributes(span, {"rag.candidate_hit_count": len(candidates)})
        except AppException:
            raise
        except Exception as exc:
            logger.warning(
                "RAG rerank candidate retrieval failed; using ordinary retrieval",
                extra={
                    "event": "rag_retrieval_degraded",
                    "error_type": type(exc).__name__,
                },
            )
            return await self.retrieve(query_text=query_text, kb_id=kb_id, top_k=limit)

        if not candidates:
            return []
        if self.reranker is None:
            return select_rerank_fallback_candidates(candidates, limit)

        try:
            with trace_span(
                "rag.rerank.native",
                {
                    "rag.kb_id": kb_id,
                    "rag.top_k": limit,
                    "rag.candidate_count": len(candidates),
                },
            ) as span:
                reranked = await self.rerank(
                    query_text=query_text,
                    candidates=candidates,
                    top_k=limit,
                )
                set_span_attributes(
                    span,
                    {
                        "rag.hit_count": len(reranked),
                    },
                )
                return reranked
        except Exception as exc:
            logger.warning(
                "RAG rerank failed; preserving candidate order",
                extra={
                    "event": "rag_rerank_degraded",
                    "error_type": type(exc).__name__,
                },
            )
            return select_rerank_fallback_candidates(candidates, limit)

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
            logger.warning(
                "RAG full-text retrieval failed; using no retrieved context",
                extra={
                    "event": "rag_retrieval_degraded",
                    "error_type": type(exc).__name__,
                },
            )
            return []

        return self._format_hits(hits, default_retrieval_mode="fulltext")

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
            logger.warning(
                "RAG hybrid retrieval failed; using no retrieved context",
                extra={
                    "event": "rag_retrieval_degraded",
                    "error_type": type(exc).__name__,
                },
            )
            return []

        return self._format_hits(hits, default_retrieval_mode="hybrid")

    @staticmethod
    def _format_hits(
        hits: Sequence[RetrievalHit | dict[str, Any] | tuple[DocumentChunk, float]],
        *,
        default_retrieval_mode: str = "vector",
    ) -> list[dict]:
        chunks: list[dict] = []
        for hit in hits:
            chunk, distance, metadata = RAGService._normalize_hit(
                hit,
                default_retrieval_mode=default_retrieval_mode,
            )
            file_obj = getattr(chunk, "__dict__", {}).get("file")
            score = max(0.0, 1.0 - distance)
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
                    "score": score,
                    "retrieval_mode": metadata["retrieval_mode"],
                    "score_kind": metadata["score_kind"],
                    "raw_score": metadata["raw_score"],
                    "evidence_score": metadata["evidence_score"],
                    "matched_by": metadata["matched_by"],
                }
            )
        return chunks

    @staticmethod
    def _normalize_hit(
        hit: RetrievalHit | dict[str, Any] | tuple[DocumentChunk, float],
        *,
        default_retrieval_mode: str,
    ) -> tuple[DocumentChunk, float, dict[str, object]]:
        if isinstance(hit, dict):
            chunk = hit["chunk"]
            distance = float(hit["distance"])
            score = max(0.0, 1.0 - distance)
            return (
                chunk,
                distance,
                {
                    "retrieval_mode": str(
                        hit.get("retrieval_mode") or default_retrieval_mode
                    ),
                    "score_kind": str(
                        hit.get("score_kind")
                        or RAGService._default_score_kind(default_retrieval_mode)
                    ),
                    "raw_score": hit.get("raw_score"),
                    "evidence_score": float(hit.get("evidence_score", score) or 0.0),
                    "matched_by": list(hit.get("matched_by") or []),
                },
            )

        legacy_hit = cast(tuple[DocumentChunk, float], hit)
        chunk, distance = legacy_hit
        score = max(0.0, 1.0 - float(distance))
        return (
            chunk,
            float(distance),
            {
                "retrieval_mode": default_retrieval_mode,
                "score_kind": RAGService._default_score_kind(default_retrieval_mode),
                "raw_score": score,
                "evidence_score": score,
                "matched_by": [default_retrieval_mode]
                if default_retrieval_mode in {"vector", "fulltext"}
                else [],
            },
        )

    @staticmethod
    def _default_score_kind(retrieval_mode: str) -> str:
        if retrieval_mode == "fulltext":
            return "fulltext_rank_similarity"
        if retrieval_mode == "hybrid":
            return "hybrid_relative_rrf"
        return "vector_similarity"

    @staticmethod
    def apply_rankings(
        *,
        candidates: list[dict],
        rankings: list[tuple[int, float]],
        limit: int,
        score_kind: str = "rerank",
        index_base: int = 1,
    ) -> list[dict]:
        selected: list[dict] = []
        selected_indexes: set[int] = set()
        indexed_scores: list[tuple[int, float, int]] = [
            (index, score, order) for order, (index, score) in enumerate(rankings)
        ]

        for index, score, _ in sorted(
            indexed_scores,
            key=lambda item: (-item[1], item[2]),
        ):
            candidate_index = index - index_base
            if candidate_index in selected_indexes:
                continue
            if not 0 <= candidate_index < len(candidates):
                continue
            chunk = dict(candidates[candidate_index])
            chunk["rerank_score"] = score
            chunk["score_kind"] = score_kind
            selected.append(chunk)
            selected_indexes.add(candidate_index)
            if len(selected) >= limit:
                return selected

        for candidate_index, candidate in enumerate(candidates):
            if candidate_index in selected_indexes:
                continue
            selected.append(candidate)
            if len(selected) >= limit:
                break
        return selected
