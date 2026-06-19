"""Worker RAG orchestrator plan tests — build_rag_plan branches and external-context gating.

职责：验证 WorkerRAGOrchestrator.build_rag_plan 的 planner 降级、kb_id 缺失与外部上下文开关分支;边界：不启动 HTTP stack、不连接真实数据库或 Redis;副作用:无。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from backend.models.schemas.chat.payloads import FeatureFlags, GenerationPayload
from backend.services.rag_planning_service import RAGExecutionPlan


async def test_build_rag_plan_planner_error_falls_back_to_default(monkeypatch) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

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


async def test_build_rag_plan_kbid_none_external_enabled_proceeds_to_planner(
    monkeypatch,
) -> None:
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator

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
