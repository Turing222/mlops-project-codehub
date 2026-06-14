"""RAG service unit tests.

职责：验证 RAGService 的全文检索、混合检索和 rerank 排序行为；边界：使用 AsyncMock 替换 vector_index_service 和 native reranker，不连接真实数据库或模型；副作用：无。
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.exceptions import app_service_error
from backend.services.rag_service import RAGService, select_rerank_fallback_candidates

pytestmark = pytest.mark.asyncio


def _build_service(reranker: object = None) -> RAGService:
    return RAGService(
        embedder=MagicMock(),
        vector_index_service=MagicMock(),
        top_k=4,
        reranker=reranker,
        rerank_candidate_count=3,
        rerank_top_k=2,
    )


def _chunk(content: str, index: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        content=content,
        source_type="file",
        file_id=uuid.uuid4(),
        message_id=None,
        file=SimpleNamespace(filename="source.md"),
        chunk_index=index,
        meta_info={},
    )


async def test_retrieve_fulltext_formats_hits_returns_results() -> None:
    service = _build_service()
    kb_id = uuid.uuid4()
    chunk = SimpleNamespace(
        id=uuid.uuid4(),
        content="chunk text",
        source_type="file",
        file_id=uuid.uuid4(),
        message_id=None,
        file=SimpleNamespace(filename="source.md"),
        chunk_index=7,
        meta_info={"page_label": "3"},
    )
    service.vector_index_service.search_chunks_for_kb_fulltext = AsyncMock(
        return_value=[(chunk, 0.2)]
    )

    result = await service.retrieve_fulltext(
        query_text="test query",
        kb_id=kb_id,
    )

    assert len(result) == 1
    assert result[0]["id"] == str(chunk.id)
    assert result[0]["content"] == "chunk text"
    assert result[0]["source_type"] == "file"
    assert result[0]["file_id"] == str(chunk.file_id)
    assert result[0]["filename"] == "source.md"
    assert result[0]["chunk_index"] == 7
    assert result[0]["meta_info"] == {"page_label": "3"}
    assert result[0]["distance"] == 0.2
    assert result[0]["score"] == 0.8
    assert result[0]["retrieval_mode"] == "fulltext"
    assert result[0]["score_kind"] == "fulltext_rank_similarity"
    assert result[0]["evidence_score"] == 0.8
    assert result[0]["matched_by"] == ["fulltext"]


async def test_retrieve_hybrid_formats_structured_hit_metadata() -> None:
    service = _build_service()
    chunk = _chunk("hybrid chunk", 0)
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[
            {
                "chunk": chunk,
                "distance": 0.3,
                "retrieval_mode": "hybrid",
                "score_kind": "hybrid_relative_rrf",
                "raw_score": 0.012,
                "evidence_score": 0.7,
                "matched_by": ["vector", "fulltext"],
            }
        ]
    )

    result = await service.retrieve_hybrid(
        query_text="test query",
        kb_id=uuid.uuid4(),
        top_k=1,
    )

    assert len(result) == 1
    assert result[0]["score"] == pytest.approx(0.7)
    assert result[0]["distance"] == 0.3
    assert result[0]["retrieval_mode"] == "hybrid"
    assert result[0]["score_kind"] == "hybrid_relative_rrf"
    assert result[0]["raw_score"] == 0.012
    assert result[0]["evidence_score"] == 0.7
    assert result[0]["matched_by"] == ["vector", "fulltext"]


async def test_retrieve_hybrid_returns_empty_on_error() -> None:
    service = _build_service()
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        side_effect=RuntimeError("db error")
    )

    result = await service.retrieve_hybrid(
        query_text="test query",
        kb_id=uuid.uuid4(),
        top_k=3,
    )

    assert result == []


async def test_retrieve_with_rerank_without_reranker_keeps_candidate_order() -> None:
    service = _build_service()
    candidates = [_chunk("alpha", 0), _chunk("beta", 1), _chunk("gamma", 2)]
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert [chunk["content"] for chunk in result] == ["alpha", "beta"]
    assert "rerank_score" not in result[0]
    assert result[0]["score_kind"] == "hybrid_relative_rrf"
    assert "evidence_score" in result[0]


async def test_retrieve_with_rerank_prefers_native_reranker() -> None:
    reranker = SimpleNamespace(rerank=AsyncMock(return_value=[(2, 0.97), (0, 0.42)]))
    service = _build_service(reranker=reranker)
    candidates = [_chunk("alpha", 0), _chunk("beta", 1), _chunk("gamma", 2)]
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert [chunk["content"] for chunk in result] == ["gamma", "alpha"]
    assert result[0]["rerank_score"] == 0.97
    assert result[0]["score_kind"] == "bifrost_rerank"
    reranker.rerank.assert_awaited_once_with(
        query_text="query",
        documents=["alpha", "beta", "gamma"],
        top_k=2,
    )


async def test_retrieve_with_rerank_without_native_reranker_returns_candidate_order() -> (
    None
):
    service = _build_service()
    candidates = [_chunk("alpha", 0), _chunk("beta", 1), _chunk("gamma", 2)]
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert [chunk["content"] for chunk in result] == ["alpha", "beta"]


async def test_retrieve_with_rerank_without_reranker_truncates_candidates() -> None:
    service = _build_service()
    candidates = [_chunk("alpha", 0), _chunk("beta", 1), _chunk("gamma", 2)]
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert [chunk["content"] for chunk in result] == ["alpha", "beta"]


async def test_retrieve_with_rerank_degrades_to_candidate_order_when_reranker_throws() -> (
    None
):
    reranker = SimpleNamespace(
        rerank=AsyncMock(side_effect=RuntimeError("reranker down"))
    )
    service = _build_service(reranker=reranker)
    candidates = [_chunk("alpha", 0), _chunk("beta", 1), _chunk("gamma", 2)]
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert [chunk["content"] for chunk in result] == ["alpha", "beta"]


async def test_retrieve_with_rerank_degrades_when_circuit_breaker_open() -> None:
    reranker = SimpleNamespace(
        rerank=AsyncMock(
            side_effect=app_service_error(
                "服务 rerank:bifrost 暂时不可用，已熔断保护",
                code="CIRCUIT_BREAKER_OPEN",
            )
        )
    )
    service = _build_service(reranker=reranker)
    candidates = [_chunk("alpha", 0), _chunk("beta", 1), _chunk("gamma", 2)]
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    # 熔断快速失败被降级为候选原始排序，不向上抛
    assert [chunk["content"] for chunk in result] == ["alpha", "beta"]


async def test_rerank_native_failure_preserves_web_candidate() -> None:
    reranker = SimpleNamespace(
        rerank=AsyncMock(side_effect=RuntimeError("reranker down"))
    )
    service = _build_service(reranker=reranker)
    candidates = [
        {"content": f"kb-{index}", "source_type": "file"} for index in range(20)
    ] + [{"content": f"web-{index}", "source_type": "web"} for index in range(4)]

    result = await service.rerank(
        query_text="query",
        candidates=candidates,
        top_k=4,
    )

    assert len(result) == 4
    assert [chunk["content"] for chunk in result[:3]] == ["kb-0", "kb-1", "kb-2"]
    assert result[3]["content"] == "web-0"


async def test_retrieve_with_rerank_preserves_web_candidate_without_reranker() -> None:
    service = _build_service(reranker=None)
    candidates = [
        _chunk("alpha", 0),
        _chunk("beta", 1),
        _chunk("gamma", 2),
        _chunk("web", 3),
    ]
    candidates[-1].source_type = "web"
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert [chunk["content"] for chunk in result] == ["alpha", "web"]


def test_apply_rankings_with_bifrost_rerank_score_kind() -> None:
    candidates = [{"content": "a"}, {"content": "b"}, {"content": "c"}]

    result = RAGService.apply_rankings(
        candidates=candidates,
        rankings=[(3, 0.9), (2, 0.5)],
        limit=2,
        score_kind="bifrost_rerank",
        index_base=1,
    )

    assert result[0]["content"] == "c"
    assert result[0]["rerank_score"] == 0.9
    assert result[0]["score_kind"] == "bifrost_rerank"
    assert result[1]["content"] == "b"
    assert result[1]["score_kind"] == "bifrost_rerank"


def test_apply_rankings_with_zero_based_index() -> None:
    candidates = [{"content": "a"}, {"content": "b"}, {"content": "c"}]

    result = RAGService.apply_rankings(
        candidates=candidates,
        rankings=[(2, 0.9), (0, 0.5)],
        limit=2,
        score_kind="bifrost_rerank",
        index_base=0,
    )

    assert result[0]["content"] == "c"
    assert result[0]["rerank_score"] == 0.9
    assert result[1]["content"] == "a"
    assert result[1]["rerank_score"] == 0.5


async def test_select_rerank_fallback_keeps_existing_web_order() -> None:
    candidates = [
        {"content": "kb-0", "source_type": "file"},
        {"content": "web-0", "source_type": "web"},
        {"content": "kb-1", "source_type": "file"},
    ]

    result = select_rerank_fallback_candidates(candidates, 2)

    assert [chunk["content"] for chunk in result] == ["kb-0", "web-0"]


async def test_select_rerank_fallback_keeps_plain_candidate_order_without_web() -> None:
    candidates = [
        {"content": "kb-0", "source_type": "file"},
        {"content": "kb-1", "source_type": "file"},
        {"content": "kb-2", "source_type": "file"},
    ]

    result = select_rerank_fallback_candidates(candidates, 2)

    assert [chunk["content"] for chunk in result] == ["kb-0", "kb-1"]
