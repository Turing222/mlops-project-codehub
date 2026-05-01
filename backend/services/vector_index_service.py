"""Vector index service.

职责：把文件切片转换为 embedding 并写入/检索知识库索引。
边界：本模块不解析原始文件、不决定知识库访问权限。
风险：替换文件切片会先删除旧索引再写入新索引，调用方应放在事务边界内。
"""

import asyncio
import hashlib
import uuid
from typing import TypedDict

from backend.contracts.interfaces import AbstractRAGEmbedder, AbstractUnitOfWork
from backend.models.orm.chunk import ChunkSourceType, DocumentChunk
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.base import BaseService

CHUNKING_VERSION = 1


class _HybridHit(TypedDict):
    """混合检索融合过程中的内部命中结构。"""

    chunk: DocumentChunk
    score: float


class VectorIndexService(BaseService[AbstractUnitOfWork]):
    """知识库向量索引写入和检索服务。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        embedder: AbstractRAGEmbedder,
        embed_batch_size: int = 32,
    ) -> None:
        super().__init__(uow)
        self.embedder = embedder
        self.embed_batch_size = max(1, embed_batch_size)

    async def replace_file_chunks(
        self,
        *,
        file_id: uuid.UUID,
        chunks: list[str],
        filename: str,
        file_path: str,
    ) -> None:
        with trace_span(
            "vector_index.replace_file_chunks",
            {
                "rag.file_id": file_id,
                "rag.filename": filename,
                "rag.chunk_count": len(chunks),
                "embedding.batch_size": self.embed_batch_size,
            },
        ) as span:
            chunk_records: list[dict] = []
            for start in range(0, len(chunks), self.embed_batch_size):
                batch = chunks[start : start + self.embed_batch_size]
                embeddings = await asyncio.to_thread(
                    self.embedder.encode_documents,
                    batch,
                )
                if len(embeddings) != len(batch):
                    raise ValueError("RAG embedding 批量返回数量与输入切片数量不一致")

                for offset, (chunk_text, embedding) in enumerate(
                    zip(batch, embeddings, strict=True)
                ):
                    idx = start + offset
                    chunk_records.append(
                        {
                            "source_type": ChunkSourceType.FILE,
                            "file_id": file_id,
                            "content": chunk_text,
                            "content_hash": hashlib.sha256(
                                chunk_text.encode("utf-8")
                            ).hexdigest(),
                            "token_count": len(chunk_text),
                            "chunk_index": idx,
                            "chunking_version": CHUNKING_VERSION,
                            "meta_info": {
                                "filename": filename,
                                "path": file_path,
                            },
                            "embedding": embedding,
                        }
                    )

            await self.uow.knowledge_repo.delete_chunks_for_file(file_id=file_id)
            await self.uow.knowledge_repo.add_chunks(chunk_records)
            set_span_attributes(
                span,
                {
                    "rag.indexed_chunk_count": len(chunk_records),
                    "embedding.output_dim": len(chunk_records[0]["embedding"])
                    if chunk_records
                    else None,
                },
            )

    async def search_chunks_for_kb(
        self,
        *,
        query_text: str,
        kb_id: uuid.UUID,
        limit: int,
    ) -> list[tuple[DocumentChunk, float]]:
        if not query_text.strip() or limit <= 0:
            return []

        with trace_span(
            "vector_index.search.vector",
            {
                "rag.kb_id": kb_id,
                "rag.top_k": limit,
                "rag.query.char_count": len(query_text),
            },
        ) as span:
            query_vector = await asyncio.to_thread(
                self.embedder.encode_query, query_text
            )
            hits = await self.uow.knowledge_repo.search_chunks_for_kb(
                query_vector=query_vector,
                kb_id=kb_id,
                limit=limit,
            )
            set_span_attributes(
                span,
                {
                    "embedding.query_dim": len(query_vector),
                    "rag.hit_count": len(hits),
                },
            )
            return hits

    async def search_chunks_for_kb_fulltext(
        self,
        *,
        query_text: str,
        kb_id: uuid.UUID,
        limit: int,
    ) -> list[tuple[DocumentChunk, float]]:
        if not query_text.strip() or limit <= 0:
            return []

        with trace_span(
            "vector_index.search.fulltext",
            {
                "rag.kb_id": kb_id,
                "rag.top_k": limit,
                "rag.query.char_count": len(query_text),
            },
        ) as span:
            hits = await self.uow.knowledge_repo.search_chunks_for_kb_fulltext(
                query_text=query_text,
                kb_id=kb_id,
                limit=limit,
            )
            set_span_attributes(span, {"rag.hit_count": len(hits)})
            return hits

    async def search_chunks_for_kb_hybrid(
        self,
        *,
        query_text: str,
        kb_id: uuid.UUID,
        limit: int,
        vector_weight: float = 0.7,
        fulltext_weight: float = 0.3,
        candidate_multiplier: int = 4,
    ) -> list[tuple[DocumentChunk, float]]:
        if not query_text.strip() or limit <= 0:
            return []

        with trace_span(
            "vector_index.search.hybrid",
            {
                "rag.kb_id": kb_id,
                "rag.top_k": limit,
                "rag.query.char_count": len(query_text),
                "rag.vector_weight": vector_weight,
                "rag.fulltext_weight": fulltext_weight,
            },
        ) as span:
            query_vector = await asyncio.to_thread(
                self.embedder.encode_query, query_text
            )
            candidate_limit = max(limit, limit * max(1, candidate_multiplier))

            vector_hits = await self.uow.knowledge_repo.search_chunks_for_kb(
                query_vector=query_vector,
                kb_id=kb_id,
                limit=candidate_limit,
            )
            fulltext_hits = await self.uow.knowledge_repo.search_chunks_for_kb_fulltext(
                query_text=query_text,
                kb_id=kb_id,
                limit=candidate_limit,
            )

            hits = self._fuse_hybrid_hits(
                vector_hits=vector_hits,
                fulltext_hits=fulltext_hits,
                limit=limit,
                vector_weight=vector_weight,
                fulltext_weight=fulltext_weight,
            )
            set_span_attributes(
                span,
                {
                    "embedding.query_dim": len(query_vector),
                    "rag.candidate_limit": candidate_limit,
                    "rag.vector_hit_count": len(vector_hits),
                    "rag.fulltext_hit_count": len(fulltext_hits),
                    "rag.hit_count": len(hits),
                },
            )
            return hits

    @staticmethod
    def _fuse_hybrid_hits(
        *,
        vector_hits: list[tuple[DocumentChunk, float]],
        fulltext_hits: list[tuple[DocumentChunk, float]],
        limit: int,
        vector_weight: float,
        fulltext_weight: float,
    ) -> list[tuple[DocumentChunk, float]]:
        if not vector_hits and not fulltext_hits:
            return []

        rrf_k = 60.0
        fused: dict[str, _HybridHit] = {}

        for rank, (chunk, _) in enumerate(vector_hits, start=1):
            key = str(chunk.id)
            item = fused.setdefault(key, {"chunk": chunk, "score": 0.0})
            item["score"] = float(item["score"]) + vector_weight / (rrf_k + rank)

        for rank, (chunk, _) in enumerate(fulltext_hits, start=1):
            key = str(chunk.id)
            item = fused.setdefault(key, {"chunk": chunk, "score": 0.0})
            item["score"] = float(item["score"]) + fulltext_weight / (rrf_k + rank)

        ranked = sorted(
            fused.values(),
            key=lambda item: float(item["score"]),
            reverse=True,
        )[:limit]
        if not ranked:
            return []

        max_score = max(float(item["score"]) for item in ranked)
        if max_score <= 0:
            return [(item["chunk"], 1.0) for item in ranked]

        # 混合分数越高越相关；对外保持与向量距离一致的“越小越好”语义。
        return [
            (
                item["chunk"],
                max(0.0, 1.0 - (float(item["score"]) / max_score)),
            )
            for item in ranked
        ]
