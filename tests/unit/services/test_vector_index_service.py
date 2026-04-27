from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.vector_index_service import VectorIndexService


@pytest.mark.asyncio
async def test_replace_file_chunks_uses_batch_embedding():
    file_id = uuid.uuid4()
    repo = SimpleNamespace(
        delete_chunks_for_file=AsyncMock(),
        add_chunks=AsyncMock(),
    )
    uow = SimpleNamespace(knowledge_repo=repo)
    embedder = MagicMock()
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

    assert embedder.encode_documents.call_count == 2
    embedder.encode_documents.assert_any_call(["chunk 1", "chunk 2"])
    embedder.encode_documents.assert_any_call(["chunk 3"])
    repo.delete_chunks_for_file.assert_awaited_once_with(file_id=file_id)
    repo.add_chunks.assert_awaited_once()

    records = repo.add_chunks.await_args.args[0]
    assert [record["chunk_index"] for record in records] == [0, 1, 2]
    assert [record["embedding"] for record in records] == [
        [0.1, 0.2],
        [0.3, 0.4],
        [0.5, 0.6],
    ]


@pytest.mark.asyncio
async def test_replace_file_chunks_rejects_mismatched_embedding_count():
    repo = SimpleNamespace(
        delete_chunks_for_file=AsyncMock(),
        add_chunks=AsyncMock(),
    )
    uow = SimpleNamespace(knowledge_repo=repo)
    embedder = MagicMock()
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
