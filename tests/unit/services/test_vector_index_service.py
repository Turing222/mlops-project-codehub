"""Vector index service unit tests.

职责：验证 VectorIndexService 的 chunk 替换、embedding 批处理和全文检索查询归一化行为；边界：使用 AsyncMock 和 SimpleNamespace，不连接真实数据库或 embedding 服务；副作用：无。
"""

from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.vector_index_service import CHUNKING_VERSION, VectorIndexService
from backend.utils.token_estimation import count_tokens

pytestmark = pytest.mark.asyncio


class _FakeUoW:
    """Minimal fake UoW that supports read_context() for search methods."""

    def __init__(self, knowledge_repo: object) -> None:
        self.knowledge_repo = knowledge_repo

    def read_context(self) -> _FakeUoW:
        return self

    async def __aenter__(self) -> _FakeUoW:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


async def test_replace_file_chunks_uses_batch_embedding_returns_replaced() -> None:
    file_id = uuid.uuid4()
    repo = SimpleNamespace(
        delete_chunks_for_file=AsyncMock(),
        add_chunks=AsyncMock(),
    )
    uow = _FakeUoW(repo)
    embedder = SimpleNamespace(encode_documents=AsyncMock())
    embedder.encode_documents.side_effect = [
        [[0.1, 0.2], [0.3, 0.4]],
        [[0.5, 0.6]],
    ]
    service = VectorIndexService(
        uow=uow,
        embedder=embedder,
        embed_batch_size=2,
    )

    await service.replace_file_chunks(
        file_id=file_id,
        chunks=["chunk 1", "chunk 2", "chunk 3"],
        filename="demo.txt",
        file_path="/tmp/demo.txt",
    )

    assert embedder.encode_documents.await_count == 2
    embedder.encode_documents.assert_any_await(["chunk 1", "chunk 2"])
    embedder.encode_documents.assert_any_await(["chunk 3"])
    repo.delete_chunks_for_file.assert_awaited_once_with(file_id=file_id)
    repo.add_chunks.assert_awaited_once()

    records = repo.add_chunks.await_args.args[0]
    assert [record["chunk_index"] for record in records] == [0, 1, 2]
    assert [record["embedding"] for record in records] == [
        [0.1, 0.2],
        [0.3, 0.4],
        [0.5, 0.6],
    ]
    assert [record["content_hash"] for record in records] == [
        hashlib.sha256(text.encode("utf-8")).hexdigest()
        for text in ["chunk 1", "chunk 2", "chunk 3"]
    ]
    assert [record["token_count"] for record in records] == [
        count_tokens(text) for text in ["chunk 1", "chunk 2", "chunk 3"]
    ]
    search_texts = [record["search_text"] for record in records]
    assert all(search_texts)
    for idx, search_text in enumerate(search_texts, start=1):
        assert "chunk" in search_text
        assert str(idx) in search_text
    assert {record["chunking_version"] for record in records} == {CHUNKING_VERSION}


async def test_replace_file_chunks_prefers_embedding_content_for_structured_chunks() -> (
    None
):
    file_id = uuid.uuid4()
    repo = SimpleNamespace(
        delete_chunks_for_file=AsyncMock(),
        add_chunks=AsyncMock(),
    )
    uow = _FakeUoW(repo)
    embedder = SimpleNamespace(encode_documents=AsyncMock())
    embedder.encode_documents.return_value = [[0.1, 0.2]]
    service = VectorIndexService(
        uow=uow,
        embedder=embedder,
        embed_batch_size=2,
    )

    await service.replace_file_chunks(
        file_id=file_id,
        chunks=[
            {
                "content": "原文内容",
                "embedding_content": "[文档: demo.md] [章节: Intro]\n原文内容",
                "meta_info": {"section_path": "Intro"},
            }
        ],
        filename="demo.md",
        file_path="/tmp/demo.md",
    )

    embedder.encode_documents.assert_awaited_once_with(
        ["[文档: demo.md] [章节: Intro]\n原文内容"]
    )
    records = repo.add_chunks.await_args.args[0]
    assert records[0]["content"] == "原文内容"
    assert records[0]["search_text"].startswith("原文内容")
    assert (
        records[0]["content_hash"]
        == hashlib.sha256(
            "[文档: demo.md] [章节: Intro]\n原文内容".encode()
        ).hexdigest()
    )
    assert records[0]["meta_info"] == {
        "filename": "demo.md",
        "path": "/tmp/demo.md",
        "section_path": "Intro",
    }


async def test_replace_file_chunks_raises_on_mismatched_embedding_count() -> None:
    repo = SimpleNamespace(
        delete_chunks_for_file=AsyncMock(),
        add_chunks=AsyncMock(),
    )
    uow = _FakeUoW(repo)
    embedder = SimpleNamespace(encode_documents=AsyncMock())
    embedder.encode_documents.return_value = [[0.1, 0.2]]
    service = VectorIndexService(
        uow=uow,
        embedder=embedder,
        embed_batch_size=2,
    )

    with pytest.raises(ValueError):
        await service.replace_file_chunks(
            file_id=uuid.uuid4(),
            chunks=["chunk 1", "chunk 2"],
            filename="demo.txt",
            file_path="/tmp/demo.txt",
        )

    repo.delete_chunks_for_file.assert_not_awaited()
    repo.add_chunks.assert_not_awaited()


async def test_prepare_chunk_records_skips_repository_write() -> None:
    file_id = uuid.uuid4()
    repo = SimpleNamespace(
        delete_chunks_for_file=AsyncMock(),
        add_chunks=AsyncMock(),
    )
    uow = _FakeUoW(repo)
    embedder = SimpleNamespace(encode_documents=AsyncMock(return_value=[[0.1, 0.2]]))
    service = VectorIndexService(
        uow=uow,
        embedder=embedder,
        embed_batch_size=2,
    )

    records = await service.prepare_chunk_records(
        file_id=file_id,
        chunks=["chunk 1"],
        filename="demo.txt",
        file_path="/tmp/demo.txt",
    )

    assert len(records) == 1
    assert records[0]["file_id"] == file_id
    assert records[0]["chunk_index"] == 0
    repo.delete_chunks_for_file.assert_not_awaited()
    repo.add_chunks.assert_not_awaited()


async def test_fulltext_search_normalizes_query_before_repo_call() -> None:
    kb_id = uuid.uuid4()
    repo = SimpleNamespace(
        search_chunks_for_kb_fulltext=AsyncMock(return_value=[]),
    )
    uow = _FakeUoW(repo)
    service = VectorIndexService(
        uow=uow,
        embedder=SimpleNamespace(encode_query=AsyncMock()),
    )

    result = await service.search_chunks_for_kb_fulltext(
        query_text="数据库 max_connections",
        kb_id=kb_id,
        limit=5,
    )

    assert result == []
    repo.search_chunks_for_kb_fulltext.assert_awaited_once()
    call_kwargs = repo.search_chunks_for_kb_fulltext.await_args.kwargs
    assert call_kwargs["kb_id"] == kb_id
    assert call_kwargs["limit"] == 5
    assert call_kwargs["normalized_query"].splitlines() == [
        "数据库 max_connections",
        "数据库",
        "max_connections",
    ]
    assert "query_text" not in call_kwargs


async def test_read_uow_factory_creates_fresh_uow_for_each_search() -> None:
    kb_id = uuid.uuid4()
    repos = [
        SimpleNamespace(search_chunks_for_kb_fulltext=AsyncMock(return_value=[])),
        SimpleNamespace(search_chunks_for_kb_fulltext=AsyncMock(return_value=[])),
    ]
    read_uows = [_FakeUoW(repo) for repo in repos]
    created_uows: list[_FakeUoW] = []

    def read_uow_factory() -> _FakeUoW:
        uow = read_uows[len(created_uows)]
        created_uows.append(uow)
        return uow

    service = VectorIndexService(
        uow=_FakeUoW(SimpleNamespace()),
        embedder=SimpleNamespace(encode_query=AsyncMock()),
        read_uow_factory=read_uow_factory,
    )

    await service.search_chunks_for_kb_fulltext(
        query_text="数据库 max_connections",
        kb_id=kb_id,
        limit=5,
    )
    await service.search_chunks_for_kb_fulltext(
        query_text="数据库 max_connections",
        kb_id=kb_id,
        limit=5,
    )

    assert created_uows == read_uows
    for repo in repos:
        repo.search_chunks_for_kb_fulltext.assert_awaited_once()


async def test_hybrid_search_returns_vector_hits_when_fulltext_empty() -> None:
    kb_id = uuid.uuid4()
    chunk_a = SimpleNamespace(id=uuid.uuid4())
    chunk_b = SimpleNamespace(id=uuid.uuid4())
    repo = SimpleNamespace(
        search_chunks_for_kb=AsyncMock(return_value=[(chunk_a, 0.1), (chunk_b, 0.2)]),
        search_chunks_for_kb_fulltext=AsyncMock(return_value=[]),
    )
    uow = _FakeUoW(repo)
    embedder = SimpleNamespace(encode_query=AsyncMock(return_value=[0.1, 0.2, 0.3]))
    service = VectorIndexService(uow=uow, embedder=embedder)

    result = await service.search_chunks_for_kb_hybrid(
        query_text="数据库 max_connections",
        kb_id=kb_id,
        limit=2,
        candidate_multiplier=3,
    )

    assert [hit["chunk"].id for hit in result] == [chunk_a.id, chunk_b.id]
    distances = [hit["distance"] for hit in result]
    assert all(0.0 <= distance <= 1.0 for distance in distances)
    assert distances[0] < distances[1]
    assert result[0]["retrieval_mode"] == "hybrid"
    assert result[0]["score_kind"] == "hybrid_vector_similarity"
    assert result[0]["matched_by"] == ["vector"]
    assert result[0]["raw_score"] == 0.9
    assert result[0]["evidence_score"] == 0.9
    embedder.encode_query.assert_awaited_once_with("数据库 max_connections")
    repo.search_chunks_for_kb.assert_awaited_once_with(
        query_vector=[0.1, 0.2, 0.3],
        kb_id=kb_id,
        limit=6,
    )
    repo.search_chunks_for_kb_fulltext.assert_awaited_once()
    fulltext_kwargs = repo.search_chunks_for_kb_fulltext.await_args.kwargs
    assert fulltext_kwargs["kb_id"] == kb_id
    assert fulltext_kwargs["limit"] == 6
    assert fulltext_kwargs["normalized_query"].splitlines() == [
        "数据库 max_connections",
        "数据库",
        "max_connections",
    ]


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_fuse_hybrid_hits_only_vector_hits() -> None:
    chunk_a = SimpleNamespace(id=uuid.uuid4())
    chunk_b = SimpleNamespace(id=uuid.uuid4())

    vector_hits = [(chunk_a, 0.1), (chunk_b, 0.3)]
    fulltext_hits: list = []

    result = VectorIndexService._fuse_hybrid_hits(
        vector_hits=vector_hits,
        fulltext_hits=fulltext_hits,
        limit=10,
        vector_weight=0.7,
        fulltext_weight=0.3,
    )

    assert len(result) == 2
    assert result[0]["chunk"].id == chunk_a.id
    assert result[1]["chunk"].id == chunk_b.id
    assert result[0]["matched_by"] == ["vector"]
    assert result[0]["score_kind"] == "hybrid_vector_similarity"
    assert result[0]["evidence_score"] == 0.9


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_fuse_hybrid_hits_uses_rrf_when_both_channels_have_hits() -> None:
    chunk_a = SimpleNamespace(id=uuid.uuid4())
    chunk_b = SimpleNamespace(id=uuid.uuid4())
    chunk_c = SimpleNamespace(id=uuid.uuid4())

    result = VectorIndexService._fuse_hybrid_hits(
        vector_hits=[(chunk_a, 0.1), (chunk_b, 0.2)],
        fulltext_hits=[(chunk_c, 4.0)],
        limit=10,
        vector_weight=0.7,
        fulltext_weight=0.3,
    )

    assert [hit["score_kind"] for hit in result] == [
        "hybrid_relative_rrf",
        "hybrid_relative_rrf",
        "hybrid_relative_rrf",
    ]
    assert [hit["chunk"].id for hit in result] == [
        chunk_a.id,
        chunk_b.id,
        chunk_c.id,
    ]


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_fuse_hybrid_hits_uses_rrf_when_both_channels_have_two_hits() -> None:
    chunk_a = SimpleNamespace(id=uuid.uuid4())
    chunk_b = SimpleNamespace(id=uuid.uuid4())
    chunk_c = SimpleNamespace(id=uuid.uuid4())

    result = VectorIndexService._fuse_hybrid_hits(
        vector_hits=[(chunk_a, 0.1), (chunk_b, 0.2)],
        fulltext_hits=[(chunk_a, 4.0), (chunk_c, 3.0)],
        limit=10,
        vector_weight=0.7,
        fulltext_weight=0.3,
    )

    assert result[0]["chunk"].id == chunk_a.id
    assert result[0]["score_kind"] == "hybrid_relative_rrf"
    assert result[0]["matched_by"] == ["fulltext", "vector"]
    assert result[0]["evidence_score"] == 0.9


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_fuse_hybrid_hits_deduplicates_sparse_dual_channel_hit() -> None:
    chunk = SimpleNamespace(id=uuid.uuid4())

    result = VectorIndexService._fuse_hybrid_hits(
        vector_hits=[(chunk, 0.2)],
        fulltext_hits=[(chunk, 4.0)],
        limit=10,
        vector_weight=0.7,
        fulltext_weight=0.3,
    )

    assert len(result) == 1
    assert result[0]["chunk"].id == chunk.id
    assert result[0]["score_kind"] == "hybrid_relative_rrf"
    assert result[0]["matched_by"] == ["fulltext", "vector"]
    assert result[0]["evidence_score"] == 0.8


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_build_single_channel_hybrid_hits_deduplicates_defensively() -> None:
    chunk = SimpleNamespace(id=uuid.uuid4())

    result = VectorIndexService._build_single_channel_hybrid_hits(
        vector_hits=[(chunk, 0.3)],
        fulltext_hits=[(chunk, 4.0)],
        limit=10,
    )

    assert len(result) == 1
    assert result[0]["chunk"].id == chunk.id
    assert result[0]["matched_by"] == ["fulltext", "vector"]
    assert result[0]["evidence_score"] == 0.8


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_fuse_hybrid_hits_filters_low_original_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.vector_index_service.ai_settings.RAG_HYBRID_MIN_SOURCE_SCORE",
        0.3,
    )
    strong_vector = SimpleNamespace(id=uuid.uuid4())
    weak_vector = SimpleNamespace(id=uuid.uuid4())
    strong_fulltext = SimpleNamespace(id=uuid.uuid4())
    weak_fulltext = SimpleNamespace(id=uuid.uuid4())

    result = VectorIndexService._fuse_hybrid_hits(
        vector_hits=[(strong_vector, 0.2), (weak_vector, 0.8)],
        fulltext_hits=[(strong_fulltext, 4.0), (weak_fulltext, 0.1)],
        limit=10,
        vector_weight=0.7,
        fulltext_weight=0.3,
    )

    assert [hit["chunk"].id for hit in result] == [
        strong_vector.id,
        strong_fulltext.id,
    ]
    assert all(hit["evidence_score"] >= 0.3 for hit in result)
