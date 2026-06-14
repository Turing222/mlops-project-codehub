"""RAG planning service unit tests.

职责：验证 RAGExecutionPlan 的值钳位和 RAGPlanningService 的模型构建与降级行为；边界：使用 FakePlanner 和 monkeypatch，不连接真实 LLM；副作用：无。
"""

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.models.schemas.chat.payloads import FeatureFlags
from backend.services.rag_planning_service import (
    _PLANNER_INSTRUCTIONS,
    RAG_PLANNER_FALLBACK_REASON,
    RAGExecutionPlan,
    RAGPlanningService,
)


class FakePlanner(RAGPlanningService):
    def __init__(self, output: object) -> None:
        super().__init__()
        self.output = output

    async def _run_agent(
        self, *, query_text: str, conversation_history: list[object], **_: object
    ) -> object:
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


class RecordingPlanner(FakePlanner):
    def __init__(self, output: object) -> None:
        super().__init__(output)
        self.calls: list[dict[str, object]] = []

    async def _run_agent(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return await super()._run_agent(**kwargs)


def test_rag_execution_plan_clamps_values_to_config_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_TOP_K",
        4,
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_RERANK_CANDIDATE_COUNT",
        20,
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_RERANK_TOP_K",
        3,
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.EXTERNAL_CONTEXT_TOP_K",
        4,
    )

    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=99,
        use_rerank=True,
        candidate_count=99,
        rerank_top_k=99,
        should_use_external_context=True,
        external_sources=["web"],
        external_top_k=99,
    ).clamped()

    assert plan.top_k == 4
    assert plan.candidate_count == 20
    assert plan.rerank_top_k == 3
    assert plan.should_use_external_context is True
    assert plan.external_sources == ["web"]
    assert plan.external_top_k == 4
    assert plan.route_confidence == 0.0
    assert plan.answer_model_tier == "balanced"


def test_rag_execution_plan_clamps_route_confidence() -> None:
    plan = RAGExecutionPlan(
        should_use_rag=False,
        selected_sources=[],
        route_confidence=1.5,
        model_route_confidence=1.5,
    ).clamped()

    assert plan.route_confidence == 1.0
    assert plan.model_route_confidence == 1.0


def test_rag_execution_plan_falls_back_to_balanced_for_low_model_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.LLM_MODEL_ROUTE_MIN_CONFIDENCE",
        0.65,
    )

    plan = RAGExecutionPlan(
        should_use_rag=False,
        selected_sources=[],
        answer_model_tier="fast",
        model_route_confidence=0.4,
    ).clamped()

    assert plan.answer_model_tier == "balanced"
    assert plan.model_route_confidence == 0.4
    assert plan.model_route_reason == "low confidence, fallback to balanced"


def test_rag_execution_plan_rejects_invalid_model_tier() -> None:
    with pytest.raises(ValidationError):
        RAGExecutionPlan(
            should_use_rag=False,
            selected_sources=[],
            answer_model_tier="tiny",
            model_route_confidence=0.9,
        )


def test_from_settings_sets_answer_route_from_selected_sources() -> None:
    rag_plan = RAGExecutionPlan.from_settings(
        has_kb=True,
        query_text="test query",
    )
    large_plan = RAGExecutionPlan.from_settings(
        has_kb=False,
        query_text="test query",
    )

    assert rag_plan.answer_route == "rag"
    assert large_plan.answer_route == "large"
    assert rag_plan.answer_model_tier == "balanced"
    assert rag_plan.model_route_confidence == 1.0


def test_refuse_route_clears_context_sources() -> None:
    plan = RAGExecutionPlan(
        selected_sources=["kb", "web"],
        should_use_rag=True,
        should_use_external_context=True,
        external_sources=["web"],
        answer_route="refuse",
        route_confidence=0.9,
    )

    assert plan.selected_sources == []
    assert plan.should_use_rag is False
    assert plan.should_use_external_context is False
    assert plan.external_sources == []


def test_large_route_with_kb_source_normalizes_to_rag() -> None:
    plan = RAGExecutionPlan(
        should_use_rag=True,
        answer_route="large",
    )

    assert plan.answer_route == "rag"
    assert plan.selected_sources == ["kb"]


def test_from_settings_enables_external_context_when_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = RAGExecutionPlan.from_settings(
        has_kb=True,
        query_text="test query",
        external_context_allowed=True,
        infra_flags=FeatureFlags(enable_external_context=True),
    )

    assert plan.should_use_external_context is True
    assert plan.external_sources == ["web"]


def test_from_settings_disables_external_context_when_not_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = RAGExecutionPlan.from_settings(
        has_kb=True,
        query_text="test query",
        external_context_allowed=False,
        infra_flags=FeatureFlags(enable_external_context=True),
    )

    assert plan.should_use_external_context is False
    assert plan.external_sources == []


def test_from_settings_off_selects_no_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = RAGExecutionPlan.from_settings(
        has_kb=True,
        query_text="test query",
        external_context_allowed=True,
        context_mode="off",
        infra_flags=FeatureFlags(enable_external_context=True),
    )

    assert plan.selected_sources == []
    assert plan.should_use_rag is False
    assert plan.should_use_external_context is False


def test_from_settings_kb_only_does_not_select_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = RAGExecutionPlan.from_settings(
        has_kb=True,
        query_text="latest public info",
        external_context_allowed=True,
        context_mode="kb_only",
        infra_flags=FeatureFlags(enable_external_context=True),
    )

    assert plan.selected_sources == ["kb"]
    assert plan.should_use_rag is True
    assert plan.should_use_external_context is False


def test_from_settings_web_only_selects_web_without_kb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = RAGExecutionPlan.from_settings(
        has_kb=False,
        query_text="latest public info",
        external_context_allowed=True,
        context_mode="web_only",
        infra_flags=FeatureFlags(enable_external_context=True),
    )

    assert plan.selected_sources == ["web"]
    assert plan.should_use_rag is False
    assert plan.should_use_external_context is True


def test_rag_planning_service_builds_plan_via_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_model(
        *, profile: object, api_key: str, max_retries: object = None
    ) -> str:
        captured["profile"] = profile
        captured["api_key"] = api_key
        captured["max_retries"] = max_retries
        return "model"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "planner-key")
    monkeypatch.setattr(
        "backend.services.rag_planning_service.create_pydantic_ai_model",
        fake_create_model,
    )

    model = RAGPlanningService(provider="deepseek")._create_model()

    assert model == "model"
    assert captured["profile"].provider == "deepseek"
    assert captured["api_key"] == "planner-key"
    assert captured["max_retries"] is None


def test_rag_planning_service_deepseek_alias_resolves_to_flash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_model(
        *, profile: object, api_key: str, max_retries: object = None
    ) -> str:
        captured["profile"] = profile
        captured["api_key"] = api_key
        return "model"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "planner-key")
    monkeypatch.setattr(
        "backend.services.rag_planning_service.create_pydantic_ai_model",
        fake_create_model,
    )

    model = RAGPlanningService(provider="deepseek")._create_model()

    assert model == "model"
    assert captured["profile"].name == "deepseek_v4_flash"
    assert captured["profile"].model == "deepseek-v4-flash"


def test_rag_planning_service_provider_fallback_to_ai_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_model(
        *, profile: object, api_key: str, max_retries: object = None
    ) -> str:
        captured["profile"] = profile
        return "model"

    monkeypatch.setenv("BIFROST_API_KEY", "bifrost-key")
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_PLANNER_PROVIDER",
        "bifrost_flash",
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.LLM_PROVIDER",
        "bifrost_pro",
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.create_pydantic_ai_model",
        fake_create_model,
    )

    model = RAGPlanningService()._create_model()

    assert model == "model"
    assert captured["profile"].name == "bifrost_v4_flash"


def test_rag_planning_service_llm_provider_fallback_uses_pro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_model(
        *, profile: object, api_key: str, max_retries: object = None
    ) -> str:
        captured["profile"] = profile
        return "model"

    monkeypatch.setenv("BIFROST_API_KEY", "chat-key")
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_PLANNER_PROVIDER",
        None,
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.LLM_PROVIDER",
        "bifrost_pro",
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.create_pydantic_ai_model",
        fake_create_model,
    )

    model = RAGPlanningService()._create_model()

    assert model == "model"
    assert captured["profile"].name == "bifrost_v4_pro"
    assert captured["profile"].model == "deepseek/deepseek-v4-pro"


def test_rag_planning_service_bifrost_flash_resolves_to_v4_flash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_model(
        *, profile: object, api_key: str, max_retries: object = None
    ) -> str:
        captured["profile"] = profile
        return "model"

    monkeypatch.setenv("BIFROST_API_KEY", "bifrost-key")
    monkeypatch.setattr(
        "backend.services.rag_planning_service.create_pydantic_ai_model",
        fake_create_model,
    )

    model = RAGPlanningService(provider="bifrost_flash")._create_model()

    assert model == "model"
    assert captured["profile"].name == "bifrost_v4_flash"
    assert captured["profile"].model == "deepseek/deepseek-v4-flash"


def test_rag_planning_service_uses_prompted_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, model: object, **kwargs: object) -> None:
            captured["model"] = model
            captured.update(kwargs)

    monkeypatch.setattr(
        "backend.services.rag_planning_service.create_pydantic_ai_model",
        lambda **_: "model",
    )
    monkeypatch.setattr("pydantic_ai.Agent", FakeAgent)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "planner-key")

    agent = RAGPlanningService(provider="deepseek")._ensure_agent()

    assert isinstance(agent, FakeAgent)
    assert captured["model"] == "model"
    assert type(captured["output_type"]).__name__ == "PromptedOutput"
    assert captured["output_type"].outputs is RAGExecutionPlan


@pytest.mark.asyncio
async def test_rag_planning_service_returns_fallback_on_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_output = ValidationError.from_exception_data(
        "RAGExecutionPlan",
        [
            {
                "type": "missing",
                "loc": ("should_use_rag",),
                "input": {},
            }
        ],
    )
    planner = FakePlanner(invalid_output)

    plan = await planner.plan(
        query_text="查询知识库",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        infra_flags=FeatureFlags(enable_rag_planner=True),
    )

    assert plan.should_use_rag is True
    assert plan.reason == RAG_PLANNER_FALLBACK_REASON
    assert plan.answer_route == "rag"


def test_planner_instructions_include_level2_route_contract() -> None:
    assert "answer_route" in _PLANNER_INSTRUCTIONS
    assert "route_confidence" in _PLANNER_INSTRUCTIONS
    assert "answer_model_tier" in _PLANNER_INSTRUCTIONS
    assert "多约束分析" in _PLANNER_INSTRUCTIONS
    assert "普通闲聊" in _PLANNER_INSTRUCTIONS


@pytest.mark.asyncio
async def test_rag_planning_service_runs_without_kb_when_external_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = RecordingPlanner(
        RAGExecutionPlan(
            should_use_rag=False,
            should_use_external_context=True,
            external_sources=["web"],
        )
    )

    plan = await planner.plan(
        query_text="今天的公开信息",
        conversation_history=[],
        kb_id=None,
        enable_external_context=True,
        infra_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_external_context=True,
        ),
    )

    assert plan.should_use_external_context is True
    assert plan.external_sources == ["web"]
    assert planner.calls[0]["has_kb"] is False
    assert planner.calls[0]["enable_external_context"] is True
    assert planner.calls[0]["context_mode"] == "auto"


@pytest.mark.asyncio
async def test_rag_planning_service_prefers_web_for_realtime_query() -> None:
    planner = RecordingPlanner(
        RAGExecutionPlan(
            context_mode="auto",
            selected_sources=["web", "kb"],
            should_use_rag=True,
            retrieval_mode="hybrid",
            should_use_external_context=True,
            external_sources=["web"],
            use_rerank=True,
            reason="需要实时天气信息，本地知识库无法提供，应使用网络搜索",
        )
    )

    plan = await planner.plan(
        query_text="今天南京天气如何",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        enable_external_context=True,
        infra_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_external_context=True,
            enable_rag_rerank=True,
        ),
    )

    assert plan.selected_sources == ["web"]
    assert plan.should_use_rag is False
    assert plan.should_use_external_context is True
    assert plan.external_sources == ["web"]
    assert plan.use_rerank is False


@pytest.mark.asyncio
async def test_rag_planning_service_keeps_kb_when_query_mentions_documents() -> None:
    planner = RecordingPlanner(
        RAGExecutionPlan(
            context_mode="auto",
            selected_sources=["kb"],
            should_use_rag=True,
            retrieval_mode="hybrid",
            reason="需要查询知识库文档",
        )
    )

    plan = await planner.plan(
        query_text="当前项目文档里怎么描述 RAG 流程",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        enable_external_context=True,
        infra_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_external_context=True,
        ),
    )

    assert plan.selected_sources == ["kb"]
    assert plan.should_use_rag is True
    assert plan.should_use_external_context is False


@pytest.mark.asyncio
async def test_rag_planning_service_web_only_runs_without_legacy_external_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = RecordingPlanner(
        RAGExecutionPlan(
            context_mode="web_only",
            selected_sources=["web"],
            should_use_rag=False,
            should_use_external_context=True,
            external_sources=["web"],
        )
    )

    plan = await planner.plan(
        query_text="今天的公开信息",
        conversation_history=[],
        kb_id=None,
        enable_external_context=False,
        context_mode="web_only",
        infra_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_external_context=True,
        ),
    )

    assert plan.selected_sources == ["web"]
    assert planner.calls[0]["context_mode"] == "web_only"


@pytest.mark.asyncio
async def test_rag_planning_service_thinking_enabled_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    profile = SimpleNamespace(extra_body={"thinking": {"type": "enabled"}})
    config = SimpleNamespace(resolve_profile=lambda _: profile)
    monkeypatch.setattr(
        "backend.services.rag_planning_service.get_llm_model_config",
        lambda: config,
    )

    # 1. Test when infra_flags has enable_rag_planner_thinking=False (default)
    planner = RAGPlanningService()
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock()
    mock_result = MagicMock()
    mock_result.output = RAGExecutionPlan(
        should_use_rag=False,
        selected_sources=[],
    )
    mock_agent.run.return_value = mock_result
    planner._agent = mock_agent

    await planner._run_agent(
        query_text="test query",
        conversation_history=[],
        has_kb=False,
        enable_external_context=False,
        context_mode="auto",
        infra_flags=FeatureFlags(enable_rag_planner_thinking=False),
    )

    assert mock_agent.run.called
    kwargs = mock_agent.run.call_args[1]
    model_settings = kwargs.get("model_settings")
    assert model_settings is not None
    assert model_settings.get("extra_body").get("thinking") == {"type": "disabled"}

    # 2. Test when infra_flags has enable_rag_planner_thinking=True
    planner_enabled = RAGPlanningService()
    mock_agent_enabled = MagicMock()
    mock_agent_enabled.run = AsyncMock()
    mock_agent_enabled.run.return_value = mock_result
    planner_enabled._agent = mock_agent_enabled

    await planner_enabled._run_agent(
        query_text="test query",
        conversation_history=[],
        has_kb=False,
        enable_external_context=False,
        context_mode="auto",
        infra_flags=FeatureFlags(enable_rag_planner_thinking=True),
    )

    assert mock_agent_enabled.run.called
    kwargs_enabled = mock_agent_enabled.run.call_args[1]
    model_settings_enabled = kwargs_enabled.get("model_settings")
    assert model_settings_enabled is not None
    assert model_settings_enabled.get("extra_body").get("thinking") == {
        "type": "enabled"
    }


@pytest.mark.asyncio
async def test_rag_planning_service_does_not_inject_thinking_for_plain_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    profile = SimpleNamespace(extra_body=None)
    config = SimpleNamespace(resolve_profile=lambda _: profile)
    monkeypatch.setattr(
        "backend.services.rag_planning_service.get_llm_model_config",
        lambda: config,
    )

    planner = RAGPlanningService(provider="gemini")
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock()
    mock_result = MagicMock()
    mock_result.output = RAGExecutionPlan(
        should_use_rag=False,
        selected_sources=[],
    )
    mock_agent.run.return_value = mock_result
    planner._agent = mock_agent

    await planner._run_agent(
        query_text="test query",
        conversation_history=[],
        has_kb=False,
        enable_external_context=False,
        context_mode="auto",
        infra_flags=FeatureFlags(enable_rag_planner_thinking=False),
    )

    assert mock_agent.run.called
    kwargs = mock_agent.run.call_args[1]
    assert "model_settings" not in kwargs
