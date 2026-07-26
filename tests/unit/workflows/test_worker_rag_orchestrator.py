"""Worker RAG orchestrator tests — RAG plan, retrieval, rerank, and fusion.

职责：验证 WorkerRAGOrchestrator 的 RAG 计划构建、检索错误处理、rerank 降级和 hybrid fusion；
边界：不启动 HTTP stack、不连接真实数据库或 Redis；副作用：无。
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from backend.models.schemas.chat.payloads import FeatureFlags, GenerationPayload
from backend.services.rag_planning_service import RAGExecutionPlan
from tests.unit.workflows.conftest import make_rag_hit


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
    assert result.refusal_decision.reason == "planner_preflight_refusal"
    assert result.search_context["planner_refusal"] is True
    assert result.search_context["refusal_type"] == "planner_preflight"
    assert result.search_context["answer_route"] == "refuse"
    assert result.search_context["route_confidence"] == 0.9
    assert "明显无法回答" not in str(result.search_context)
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


async def test_prepare_context_planner_preflight_refusal_uses_stable_reason(
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
    assert result.refusal_decision.reason == "planner_preflight_refusal"
    assert "问题超出知识库范围" not in str(result)
    rag_service.retrieve.assert_not_awaited()


async def test_prepare_context_planner_preflight_refusal_stays_stable_without_reason(
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
    assert result.refusal_decision.reason == "planner_preflight_refusal"
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
    assert result.refusal_decision.reason == "planner_preflight_refusal"
    assert "边界值拒答" not in str(result)
    rag_service.retrieve.assert_not_awaited()
