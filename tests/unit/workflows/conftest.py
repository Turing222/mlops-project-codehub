"""Shared fixtures and helpers for tests/unit/workflows/.

职责：提供 workflows 测试复用的 FakeAsyncUow、fake_chat_uow、make_rag_hit；
边界：不 import backend.main，不启动 HTTP stack 或真实外部依赖；副作用：无。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest


class FakeAsyncUow:
    """Minimal async UoW context manager with empty repos."""

    async def __aenter__(self) -> FakeAsyncUow:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return


class FakeChatUow:
    """Async UoW with chat_repo, user_repo and credit_repo AsyncMocks."""

    def __init__(self) -> None:
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        self.chat_repo = AsyncMock()
        self.chat_repo.get_message = AsyncMock(return_value=None)
        self.user_repo = AsyncMock()
        self.credit_repo = AsyncMock()

        credit_account = MagicMock()
        credit_account.balance = 1000
        self.credit_repo.get_account_with_lock = AsyncMock(return_value=credit_account)
        self.credit_repo.create_account = AsyncMock(return_value=credit_account)
        self.credit_repo.get_transaction_by_idempotency_key = AsyncMock(
            return_value=None
        )
        self.credit_repo.get_usage_record_by_chat_message_id = AsyncMock(
            return_value=None
        )

        @asynccontextmanager
        async def _noop_savepoint():
            yield self

        self.savepoint = _noop_savepoint

    async def __aenter__(self) -> FakeChatUow:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return


@pytest.fixture
def fake_async_uow() -> FakeAsyncUow:
    return FakeAsyncUow()


@pytest.fixture
def fake_chat_uow() -> FakeChatUow:
    return FakeChatUow()


def make_rag_hit(
    *,
    content: str = "worker-side context",
    index: int = 0,
    score: float | None = None,
    distance: float | None = None,
    retrieval_mode: str = "vector",
    evidence_score: float | None = None,
    matched_by: list[str] | None = None,
    rerank_score: float | None = None,
) -> dict:
    _score = 0.9 - index * 0.1 if score is None else score
    _distance = 0.1 + index * 0.1 if distance is None else distance
    hit = {
        "id": str(uuid.uuid4()),
        "content": content,
        "source_type": "file",
        "file_id": str(uuid.uuid4()),
        "message_id": None,
        "filename": f"doc-{index}.md",
        "chunk_index": index,
        "meta_info": {},
        "distance": _distance,
        "score": _score,
        "retrieval_mode": retrieval_mode,
        "score_kind": (
            "vector_similarity"
            if retrieval_mode == "vector"
            else "fulltext_rank_similarity"
            if retrieval_mode == "fulltext"
            else "hybrid_relative_rrf"
        ),
        "raw_score": _score,
        "evidence_score": _score if evidence_score is None else evidence_score,
        "matched_by": matched_by or [retrieval_mode],
    }
    if rerank_score is not None:
        hit["rerank_score"] = rerank_score
    return hit
