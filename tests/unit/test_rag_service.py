import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.rag_service import RAGService


def _build_service() -> RAGService:
    service = RAGService(
        uow=MagicMock(),
        embedder=MagicMock(),
        top_k=4,
    )
    service.vector_index_service = MagicMock()
    return service


@pytest.mark.asyncio
async def test_retrieve_fulltext_formats_hits():
    service = _build_service()
    kb_id = uuid.uuid4()
    chunk = SimpleNamespace(
        id=uuid.uuid4(),
        content="chunk text",
        source_type="file",
        file_id=uuid.uuid4(),
        message_id=None,
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
    assert result[0]["distance"] == 0.2
    assert result[0]["score"] == 0.8


@pytest.mark.asyncio
async def test_retrieve_hybrid_returns_empty_on_error():
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
