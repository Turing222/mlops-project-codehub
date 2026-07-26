"""Worker RAG orchestrator retrieval tests — candidate retrieval, rerank fallback, external context.

职责：验证 WorkerRAGOrchestrator 的检索错误处理、rerank 降级与外部上下文检索;边界：不启动 HTTP stack、不连接真实数据库或 Redis;副作用:无。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from backend.models.schemas.chat.payloads import FeatureFlags, GenerationPayload
from backend.services.rag_planning_service import RAGExecutionPlan
from tests.unit.workflows.conftest import make_rag_hit


async def test_retrieve_rag_candidates_connection_error_returns_empty(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        kb_id=uuid.uuid4(),
        conversation_history=[],
        feature_flags=FeatureFlags(enable_rag_rerank=False),
    )

    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(side_effect=ConnectionError("DB down"))

    rag_plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="vector",
        top_k=4,
    )

    orchestrator = WorkerRAGOrchestrator(rag_service=rag_service)
    result = await orchestrator.retrieve_rag_candidates(payload, rag_plan)

    assert result == []
    rag_service.retrieve.assert_awaited_once()


async def test_rerank_candidates_if_enabled_rerank_error_falls_back(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

    calls: list[dict] = []

    class _FakeSlot:
        def __init__(self, attrs: dict | None) -> None:
            self.attrs = attrs

        async def __aenter__(self) -> None:
            calls.append(self.attrs)

        async def __aexit__(self, *args) -> None:
            pass

    monkeypatch.setattr(
        "backend.application.chat.worker_rag_orchestrator.llm_concurrency_slot",
        _FakeSlot,
    )

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        conversation_history=[],
    )

    candidates = [make_rag_hit(content=f"chunk-{i}", index=i) for i in range(3)]

    rag_plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="vector",
        top_k=4,
        use_rerank=True,
        rerank_top_k=2,
        candidate_count=20,
    )

    rag_service = MagicMock()
    rag_service.rerank = AsyncMock(side_effect=RuntimeError("rerank failed"))

    orchestrator = WorkerRAGOrchestrator(rag_service=rag_service)
    result = await orchestrator.rerank_candidates_if_enabled(
        payload, candidates, rag_plan
    )

    assert len(result) == 2
    assert result[0]["content"] == "chunk-0"
    assert result[1]["content"] == "chunk-1"


async def test_rerank_candidates_if_enabled_fallback_preserves_web_hit(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

    class _FakeSlot:
        def __init__(self, attrs: dict | None) -> None:
            self.attrs = attrs

        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args) -> None:
            pass

    monkeypatch.setattr(
        "backend.application.chat.worker_rag_orchestrator.llm_concurrency_slot",
        _FakeSlot,
    )

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        conversation_history=[],
    )
    kb_candidates = [
        make_rag_hit(content=f"kb-{index}", index=index) for index in range(20)
    ]
    web_candidates = [
        {
            **make_rag_hit(content=f"web-{index}", index=index),
            "source_type": "web",
            "file_id": f"https://example.com/{index}",
            "title": f"Web {index}",
        }
        for index in range(4)
    ]

    rag_plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=True,
        rerank_top_k=4,
        candidate_count=20,
        selected_sources=["kb", "web"],
    )

    rag_service = MagicMock()
    rag_service.rerank = AsyncMock(side_effect=RuntimeError("rerank failed"))

    orchestrator = WorkerRAGOrchestrator(rag_service=rag_service)
    result = await orchestrator.rerank_candidates_if_enabled(
        payload, [*kb_candidates, *web_candidates], rag_plan
    )

    assert len(result) == 4
    assert [chunk["content"] for chunk in result[:3]] == ["kb-0", "kb-1", "kb-2"]
    assert result[3]["content"] == "web-0"
    assert result[3]["source_type"] == "web"


async def test_external_context_candidates_are_added_when_planned(monkeypatch) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.services.external_context_service import ExternalContextChunk

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="latest docs",
        conversation_history=[],
        enable_external_context=True,
        feature_flags=FeatureFlags(enable_external_context=True),
    )
    plan = RAGExecutionPlan(
        should_use_rag=False,
        should_use_external_context=True,
        external_sources=["web"],
        external_top_k=2,
    )
    provider = MagicMock()
    provider.provider_name = "tavily"
    provider.search = AsyncMock(
        return_value=[
            ExternalContextChunk(
                id="web:1",
                content="fresh public context",
                provider="tavily",
                title="Fresh result",
                url="https://example.com/fresh",
                score=0.8,
            )
        ]
    )

    orchestrator = WorkerRAGOrchestrator(external_context_provider=provider)
    result = await orchestrator.retrieve_external_context_candidates(payload, plan)

    assert result[0]["source_type"] == "web"
    assert result[0]["provider"] == "tavily"
    assert result[0]["url"] == "https://example.com/fresh"
    provider.search.assert_awaited_once_with(query_text="latest docs", top_k=2)


async def test_retrieve_external_context_returns_empty_when_provider_none(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        enable_external_context=True,
        conversation_history=[],
        feature_flags=FeatureFlags(enable_external_context=True),
    )
    plan = RAGExecutionPlan(
        should_use_rag=False,
        should_use_external_context=True,
        external_sources=["web"],
        external_top_k=2,
    )

    orchestrator = WorkerRAGOrchestrator(external_context_provider=None)
    result = await orchestrator.retrieve_external_context_candidates(payload, plan)

    assert result == []


async def test_retrieve_external_context_returns_empty_when_disabled(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

    provider = MagicMock()
    provider.search = AsyncMock(return_value=[])

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        enable_external_context=True,
        conversation_history=[],
        feature_flags=FeatureFlags(enable_external_context=False),
    )
    plan = RAGExecutionPlan(
        should_use_rag=False,
        should_use_external_context=True,
        external_sources=["web"],
        external_top_k=2,
    )

    orchestrator = WorkerRAGOrchestrator(external_context_provider=provider)
    result = await orchestrator.retrieve_external_context_candidates(payload, plan)

    assert result == []
    provider.search.assert_not_awaited()


async def test_retrieve_external_context_uses_selected_sources_not_legacy_flag(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.services.external_context_service import ExternalContextChunk

    provider = MagicMock()
    provider.provider_name = "tavily"
    provider.search = AsyncMock(
        return_value=[
            ExternalContextChunk(
                id="web:1",
                content="fresh context",
                provider="tavily",
                score=0.8,
            )
        ]
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="latest",
        context_mode="web_only",
        enable_external_context=False,
        conversation_history=[],
        feature_flags=FeatureFlags(enable_external_context=True),
    )
    plan = RAGExecutionPlan(
        context_mode="web_only",
        selected_sources=["web"],
        should_use_rag=False,
        should_use_external_context=True,
        external_sources=["web"],
        external_top_k=1,
    )

    orchestrator = WorkerRAGOrchestrator(external_context_provider=provider)
    result = await orchestrator.retrieve_external_context_candidates(payload, plan)

    assert len(result) == 1
    provider.search.assert_awaited_once_with(query_text="latest", top_k=1)


async def test_retrieve_external_context_skips_when_web_not_selected(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

    provider = MagicMock()
    provider.search = AsyncMock(return_value=[])
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="latest",
        context_mode="kb_only",
        enable_external_context=True,
        conversation_history=[],
        feature_flags=FeatureFlags(enable_external_context=True),
    )
    plan = RAGExecutionPlan(
        context_mode="kb_only",
        selected_sources=["kb"],
        should_use_rag=True,
        should_use_external_context=False,
    )

    orchestrator = WorkerRAGOrchestrator(external_context_provider=provider)
    result = await orchestrator.retrieve_external_context_candidates(payload, plan)

    assert result == []
    provider.search.assert_not_awaited()


async def test_retrieve_external_context_provider_error_returns_empty(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

    provider = MagicMock()
    provider.provider_name = "tavily"
    provider.search = AsyncMock(side_effect=ConnectionError("API down"))

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        enable_external_context=True,
        conversation_history=[],
        feature_flags=FeatureFlags(enable_external_context=True),
    )
    plan = RAGExecutionPlan(
        should_use_rag=False,
        should_use_external_context=True,
        external_sources=["web"],
        external_top_k=2,
    )

    orchestrator = WorkerRAGOrchestrator(external_context_provider=provider)
    result = await orchestrator.retrieve_external_context_candidates(payload, plan)

    assert result == []
