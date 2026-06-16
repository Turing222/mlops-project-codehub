"""Worker RAG orchestrator step callback tests."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
from backend.models.schemas.chat.payloads import FeatureFlags, GenerationPayload
from backend.services.rag_evidence_policy import RAGEvidenceDecision
from tests.unit.workflows.conftest import make_rag_hit

pytestmark = pytest.mark.asyncio


async def test_prepare_context_emits_step_callbacks_in_order() -> None:
    kb_id = uuid.uuid4()
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test query",
        kb_id=kb_id,
        conversation_history=[],
        feature_flags=FeatureFlags(enable_rag_rerank=False),
    )

    rag_service = MagicMock()
    rag_service.retrieve_fulltext = AsyncMock(return_value=[make_rag_hit()])
    rag_service.retrieve = AsyncMock(return_value=[])

    mock_assembled_prompt = SimpleNamespace(total_tokens=42, messages=[])
    mock_context_builder = MagicMock()
    mock_context_builder.build_from_chunks.return_value = SimpleNamespace(
        assembled_prompt=mock_assembled_prompt,
        search_context={"metrics": {"context_build_ms": 5}},
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        chat_context_builder=mock_context_builder,
    )
    orchestrator.rag_evidence_policy.evaluate = MagicMock(
        return_value=RAGEvidenceDecision(
            should_refuse=False,
            reason="",
            hit_count=1,
        )
    )
    emitted: list[tuple[str, str]] = []

    async def on_step(
        step: str,
        status: str,
        metrics: dict[str, object] | None = None,
    ) -> None:
        emitted.append((step, status))

    await orchestrator.prepare_context(payload, on_step=on_step)

    assert emitted[0] == ("router-judge", "running")
    assert ("router-judge", "done") in emitted
    assert ("kb-search", "running") in emitted
    assert ("kb-search", "done") in emitted
    assert ("organize-citations", "running") not in emitted
