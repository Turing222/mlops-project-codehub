"""Worker RAG orchestrator tests — RAG plan, retrieval, rerank, and fusion.

职责：验证 WorkerRAGOrchestrator 的 RAG 计划构建、检索错误处理、rerank 降级和 hybrid fusion；
边界：不启动 HTTP stack、不连接真实数据库或 Redis；副作用：无。
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.schemas.chat.payloads import FeatureFlags, GenerationPayload
from backend.services.rag_planning_service import RAGExecutionPlan
from tests.unit.workflows.conftest import make_rag_hit

pytestmark = pytest.mark.asyncio


async def test_prepare_context_kb_id_none_empty_retrieval_no_refusal(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.context_state import ContextState
    from backend.models.schemas.chat.payloads import GenerationPayload

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test query",
        conversation_history=[],
        context_state=ContextState(decisions=["使用会话记忆"]),
    )

    rag_service = MagicMock()
    rag_service.retrieve_fulltext = AsyncMock(return_value=[])
    rag_service.retrieve = AsyncMock(return_value=[])

    mock_assembled_prompt = SimpleNamespace(total_tokens=42, messages=[])
    mock_context_builder = MagicMock()
    mock_context_builder.build_from_chunks.return_value = SimpleNamespace(
        assembled_prompt=mock_assembled_prompt,
        search_context={"key": "val"},
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        chat_context_builder=mock_context_builder,
    )

    result = await orchestrator.prepare_context(payload)

    assert result.refusal_decision is None
    assert result.assembled_prompt is not None
    assert (
        mock_context_builder.build_from_chunks.call_args.kwargs["context_state"]
        == payload.context_state
    )


async def test_build_rag_plan_planner_error_falls_back_to_default(monkeypatch) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test query",
        kb_id=uuid.uuid4(),
        conversation_history=[],
        feature_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_rag_rerank=False,
        ),
    )

    planner = MagicMock()
    planner.plan = AsyncMock(side_effect=ValueError("LLM API failed"))

    orchestrator = WorkerRAGOrchestrator(
        rag_planning_service=planner,
    )

    plan, planner_used = await orchestrator.build_rag_plan(payload)

    assert isinstance(plan, RAGExecutionPlan)
    assert plan.should_use_rag is True
    assert planner_used is False


async def test_retrieve_rag_candidates_connection_error_returns_empty(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

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
    from backend.models.schemas.chat.payloads import GenerationPayload

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
    from backend.models.schemas.chat.payloads import GenerationPayload

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


async def test_prepare_context_refusal_search_context_includes_evidence_fields(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.5,
    )

    low_evidence_hit = make_rag_hit(
        retrieval_mode="hybrid",
        score=1.0,
        evidence_score=0.2,
        matched_by=["vector"],
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        kb_id=uuid.uuid4(),
        conversation_history=[],
        rag_candidates=[low_evidence_hit],
        feature_flags=FeatureFlags(enable_rag_refusal=True),
    )

    orchestrator = WorkerRAGOrchestrator()
    result = await orchestrator.prepare_context(payload)

    assert result.refusal_decision is not None
    assert result.search_context is not None
    assert result.search_context["rag_refusal"] is True
    assert result.search_context["reason"] == "RAG hybrid 证据不足"
    first_chunk = result.search_context["chunks"][0]
    assert first_chunk["retrieval_mode"] == "hybrid"
    assert first_chunk["evidence_score"] == 0.2
    assert first_chunk["matched_by"] == ["vector"]


async def test_prepare_context_hybrid_rerank_uses_rerank_score_for_policy(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.5,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RERANK_SCORE",
        4.0,
    )

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        kb_id=uuid.uuid4(),
        conversation_history=[],
        feature_flags=FeatureFlags(enable_rag_refusal=True),
    )
    candidate = make_rag_hit(
        retrieval_mode="hybrid",
        score=1.0,
        evidence_score=0.1,
        matched_by=["vector"],
    )
    reranked = dict(candidate, rerank_score=5.0, score_kind="rerank_score")
    rag_service = MagicMock()
    rag_service.retrieve_hybrid = AsyncMock(return_value=[candidate])
    rag_service.rerank = AsyncMock(return_value=[reranked])
    context_builder = MagicMock()
    context_builder.build_from_chunks.return_value = SimpleNamespace(
        assembled_prompt=SimpleNamespace(total_tokens=42, messages=[]),
        search_context={"chunks": [{"rerank_score": 5.0}]},
    )
    rag_plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=True,
        candidate_count=20,
        rerank_top_k=4,
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=rag_plan)
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        kb_id=uuid.uuid4(),
        conversation_history=[],
        feature_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_rag_refusal=True,
        ),
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        rag_planning_service=planner,
        chat_context_builder=context_builder,
    )
    result = await orchestrator.prepare_context(payload)

    assert result.refusal_decision is None
    rag_service.rerank.assert_awaited_once()
    context_builder.build_from_chunks.assert_called_once()
    assert (
        context_builder.build_from_chunks.call_args.kwargs["rag_chunks"][0][
            "rerank_score"
        ]
        == 5.0
    )


async def test_prepare_context_planner_preflight_refusal_skips_retrieval(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    monkeypatch.setattr(
        "backend.application.chat.worker_rag_orchestrator.ai_settings.RAG_PLANNER_REFUSAL_CONFIDENCE_THRESHOLD",
        0.85,
    )

    plan = RAGExecutionPlan(
        should_use_rag=True,
        answer_route="refuse",
        route_confidence=0.9,
        planner_refusal_reason="明显无法回答",
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)
    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(return_value=[make_rag_hit()])

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    result = await orchestrator.prepare_context(
        GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="test",
            kb_id=uuid.uuid4(),
            conversation_history=[],
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=True,
            ),
        )
    )

    assert result.refusal_decision is not None
    assert result.refusal_decision.reason == "明显无法回答"
    assert result.search_context["planner_refusal"] is True
    assert result.search_context["refusal_type"] == "planner_preflight"
    assert result.search_context["answer_route"] == "refuse"
    assert result.search_context["route_confidence"] == 0.9
    rag_service.retrieve.assert_not_awaited()


async def test_prepare_context_low_confidence_refuse_continues_existing_flow(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    plan = RAGExecutionPlan(
        should_use_rag=True,
        answer_route="refuse",
        route_confidence=0.7,
        planner_refusal_reason="不够确定",
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)
    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(return_value=[make_rag_hit()])
    context_builder = MagicMock()
    context_builder.build_from_chunks.return_value = SimpleNamespace(
        assembled_prompt=SimpleNamespace(total_tokens=42, messages=[]),
        search_context={"chunks": []},
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        rag_planning_service=planner,
        chat_context_builder=context_builder,
    )
    result = await orchestrator.prepare_context(
        GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="test",
            kb_id=uuid.uuid4(),
            conversation_history=[],
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=True,
                enable_rag_refusal=False,
            ),
        )
    )

    assert result.refusal_decision is None
    rag_service.retrieve.assert_awaited_once()
    context_builder.build_from_chunks.assert_called_once()


async def test_prepare_context_planner_large_route_skips_rag(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    plan = RAGExecutionPlan(
        selected_sources=[],
        should_use_rag=False,
        answer_route="large",
        route_confidence=0.9,
        reason="无需知识库",
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)
    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(return_value=[make_rag_hit()])
    context_builder = MagicMock()
    context_builder.build_from_chunks.return_value = SimpleNamespace(
        assembled_prompt=SimpleNamespace(total_tokens=42, messages=[]),
        search_context=None,
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        rag_planning_service=planner,
        chat_context_builder=context_builder,
    )
    result = await orchestrator.prepare_context(
        GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            kb_id=uuid.uuid4(),
            conversation_history=[],
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=True,
            ),
        )
    )

    assert result.refusal_decision is None
    rag_service.retrieve.assert_not_awaited()
    context_builder.build_from_chunks.assert_called_once()


async def test_prepare_context_routing_disabled_ignores_refuse_route(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    plan = RAGExecutionPlan(
        should_use_rag=True,
        answer_route="refuse",
        route_confidence=1.0,
        planner_refusal_reason="ignored",
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)
    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(return_value=[make_rag_hit()])
    context_builder = MagicMock()
    context_builder.build_from_chunks.return_value = SimpleNamespace(
        assembled_prompt=SimpleNamespace(total_tokens=42, messages=[]),
        search_context={"chunks": []},
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        rag_planning_service=planner,
        chat_context_builder=context_builder,
    )
    result = await orchestrator.prepare_context(
        GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="test",
            kb_id=uuid.uuid4(),
            conversation_history=[],
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=False,
                enable_rag_refusal=False,
            ),
        )
    )

    assert result.refusal_decision is None
    rag_service.retrieve.assert_awaited_once()


async def test_prepare_context_planner_preflight_refusal_falls_back_to_plan_reason(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    monkeypatch.setattr(
        "backend.application.chat.worker_rag_orchestrator.ai_settings.RAG_PLANNER_REFUSAL_CONFIDENCE_THRESHOLD",
        0.85,
    )

    plan = RAGExecutionPlan(
        should_use_rag=True,
        answer_route="refuse",
        route_confidence=0.9,
        planner_refusal_reason="",
        reason="问题超出知识库范围",
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)
    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(return_value=[make_rag_hit()])

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    result = await orchestrator.prepare_context(
        GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="test",
            kb_id=uuid.uuid4(),
            conversation_history=[],
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=True,
            ),
        )
    )

    assert result.refusal_decision is not None
    assert result.refusal_decision.reason == "问题超出知识库范围"
    rag_service.retrieve.assert_not_awaited()


async def test_prepare_context_planner_preflight_refusal_falls_back_to_default_text(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

    monkeypatch.setattr(
        "backend.application.chat.worker_rag_orchestrator.ai_settings.RAG_PLANNER_REFUSAL_CONFIDENCE_THRESHOLD",
        0.85,
    )

    plan = RAGExecutionPlan(
        should_use_rag=True,
        answer_route="refuse",
        route_confidence=0.9,
        planner_refusal_reason="",
        reason="",
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)
    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(return_value=[make_rag_hit()])

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    result = await orchestrator.prepare_context(
        GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="test",
            kb_id=uuid.uuid4(),
            conversation_history=[],
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=True,
            ),
        )
    )

    assert result.refusal_decision is not None
    assert result.refusal_decision.reason == "RAG planner 前置拒答"
    rag_service.retrieve.assert_not_awaited()


async def test_prepare_context_existing_rag_candidates_skips_preflight_refusal(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    plan = RAGExecutionPlan(
        should_use_rag=True,
        answer_route="refuse",
        route_confidence=0.95,
        planner_refusal_reason="应拒答",
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)
    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(return_value=[make_rag_hit()])
    context_builder = MagicMock()
    context_builder.build_from_chunks.return_value = SimpleNamespace(
        assembled_prompt=SimpleNamespace(total_tokens=42, messages=[]),
        search_context={"chunks": []},
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        rag_planning_service=planner,
        chat_context_builder=context_builder,
    )
    result = await orchestrator.prepare_context(
        GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="test",
            kb_id=uuid.uuid4(),
            conversation_history=[],
            rag_candidates=[{"content": "pre-fetched", "score": 0.9}],
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=True,
                enable_rag_refusal=False,
            ),
        )
    )

    assert result.refusal_decision is None
    rag_service.retrieve.assert_not_awaited()
    context_builder.build_from_chunks.assert_called_once()


async def test_prepare_context_confidence_at_threshold_triggers_refusal(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    monkeypatch.setattr(
        "backend.application.chat.worker_rag_orchestrator.ai_settings.RAG_PLANNER_REFUSAL_CONFIDENCE_THRESHOLD",
        0.85,
    )

    plan = RAGExecutionPlan(
        should_use_rag=True,
        answer_route="refuse",
        route_confidence=0.85,
        planner_refusal_reason="边界值拒答",
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)
    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(return_value=[make_rag_hit()])

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    result = await orchestrator.prepare_context(
        GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="test",
            kb_id=uuid.uuid4(),
            conversation_history=[],
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=True,
            ),
        )
    )

    assert result.refusal_decision is not None
    assert result.refusal_decision.reason == "边界值拒答"
    rag_service.retrieve.assert_not_awaited()


async def test_external_context_candidates_are_added_when_planned(monkeypatch) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload
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


async def test_build_rag_plan_kbid_none_external_enabled_proceeds_to_planner(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    planned = RAGExecutionPlan(
        should_use_rag=False,
        should_use_external_context=True,
        external_sources=["web"],
        external_top_k=3,
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=planned)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="latest news",
        kb_id=None,
        enable_external_context=True,
        conversation_history=[],
        feature_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_rag_rerank=False,
            enable_external_context=True,
        ),
    )

    orchestrator = WorkerRAGOrchestrator(rag_planning_service=planner)
    plan, planner_used = await orchestrator.build_rag_plan(payload)

    assert planner_used is True
    assert plan.should_use_external_context is True
    planner.plan.assert_awaited_once_with(
        query_text="latest news",
        conversation_history=[],
        kb_id=None,
        enable_external_context=True,
        context_mode=None,
        infra_flags=payload.feature_flags,
    )


async def test_build_rag_plan_kbid_none_external_disabled_returns_default(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test query",
        kb_id=None,
        enable_external_context=False,
        conversation_history=[],
        feature_flags=FeatureFlags(enable_rag_planner=True),
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_planning_service=MagicMock(),
    )
    plan, planner_used = await orchestrator.build_rag_plan(payload)

    assert planner_used is False
    assert plan.should_use_rag is False


async def test_build_rag_plan_blank_query_returns_default(monkeypatch) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="   ",
        kb_id=uuid.uuid4(),
        conversation_history=[],
        feature_flags=FeatureFlags(enable_rag_planner=True),
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_planning_service=MagicMock(),
    )
    plan, planner_used = await orchestrator.build_rag_plan(payload)

    assert planner_used is False


async def test_build_rag_plan_planner_receives_enable_external_context(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    planned = RAGExecutionPlan(
        should_use_rag=True,
        should_use_external_context=True,
        retrieval_mode="vector",
        top_k=4,
        external_sources=["web"],
        external_top_k=2,
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=planned)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test query",
        kb_id=uuid.uuid4(),
        enable_external_context=True,
        conversation_history=[],
        feature_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_rag_rerank=False,
        ),
    )

    orchestrator = WorkerRAGOrchestrator(rag_planning_service=planner)
    await orchestrator.build_rag_plan(payload)

    planner.plan.assert_awaited_once()
    assert planner.plan.await_args.kwargs["enable_external_context"] is True
    assert planner.plan.await_args.kwargs["context_mode"] is None


async def test_build_rag_plan_default_plan_includes_external_context_allowed(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test query",
        kb_id=None,
        enable_external_context=True,
        conversation_history=[],
        feature_flags=FeatureFlags(
            enable_rag_planner=False,
            enable_external_context=True,
        ),
    )

    orchestrator = WorkerRAGOrchestrator()
    plan, planner_used = await orchestrator.build_rag_plan(payload)

    assert planner_used is False
    assert plan.should_use_external_context is True
    assert plan.selected_sources == ["web"]


async def test_build_rag_plan_web_only_context_mode_allows_external_without_legacy_flag(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="latest news",
        kb_id=None,
        context_mode="web_only",
        enable_external_context=False,
        conversation_history=[],
        feature_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_external_context=True,
        ),
    )

    planned = RAGExecutionPlan(
        context_mode="web_only",
        selected_sources=["web"],
        should_use_rag=False,
        should_use_external_context=True,
        external_sources=["web"],
        external_top_k=2,
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=planned)

    orchestrator = WorkerRAGOrchestrator(rag_planning_service=planner)
    plan, planner_used = await orchestrator.build_rag_plan(payload)

    assert planner_used is True
    assert plan.selected_sources == ["web"]
    planner.plan.assert_awaited_once()
    assert planner.plan.await_args.kwargs["context_mode"] == "web_only"


async def test_retrieve_external_context_returns_empty_when_provider_none(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

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
    from backend.models.schemas.chat.payloads import GenerationPayload

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
    from backend.models.schemas.chat.payloads import GenerationPayload
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
    from backend.models.schemas.chat.payloads import GenerationPayload

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
    from backend.models.schemas.chat.payloads import GenerationPayload

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
