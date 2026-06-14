"""Pydantic AI LLM service unit tests.

职责：验证 agent 输入构造、provider factory 和 extra_body 合并；边界：使用 monkeypatch/stub 替换 SDK 调用，不访问真实 LLM；副作用：无。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.ai.providers.llm.pydantic_ai_models import create_pydantic_ai_model
from backend.ai.providers.llm.pydantic_ai_service import PydanticAILLMService
from backend.ai.providers.llm.routing_service import LLMRoutingService
from backend.config.llm import get_llm_model_config
from backend.core.exceptions import AppException
from backend.models.schemas.chat.dto import LLMQueryDTO


def make_query(messages: list[dict] | None = None) -> LLMQueryDTO:
    return LLMQueryDTO(
        session_id=uuid.uuid4(),
        query_text="当前问题",
        conversation_history=messages or [],
    )


def test_build_agent_input_splits_system_history_and_current_user() -> None:
    messages = [
        {"role": "system", "content": "你是专业助手。"},
        {"role": "user", "content": "上一问"},
        {"role": "assistant", "content": "上一答"},
        {"role": "user", "content": "当前问题"},
    ]

    instructions, prompt = PydanticAILLMService._build_agent_input(make_query(messages))

    assert instructions == "你是专业助手。"
    assert "用户: 上一问" in prompt
    assert "助手: 上一答" in prompt
    assert prompt.endswith("当前问题")


@pytest.mark.asyncio
async def test_generate_response_uses_pydantic_agent(monkeypatch) -> None:
    service = PydanticAILLMService(
        api_key="test-key", model_name="gemini-test", provider_name="gemini"
    )
    captured = {}

    class FakeAgent:
        async def run(self, prompt: str, **kwargs):
            captured["prompt"] = prompt
            captured["model_settings"] = kwargs.get("model_settings")
            return SimpleNamespace(output="Gemini answer")

    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())

    result = await service.generate_response(make_query())

    assert captured["prompt"] == "当前问题"
    assert captured["model_settings"] is None
    assert result.content == "Gemini answer"
    assert result.success is True


@pytest.mark.asyncio
async def test_generate_response_reads_provider_usage(monkeypatch) -> None:
    service = PydanticAILLMService(
        api_key="test-key", model_name="gemini-test", provider_name="gemini"
    )

    class FakeAgent:
        async def run(self, prompt: str, **kwargs):
            return SimpleNamespace(
                output="Gemini answer",
                usage=lambda: SimpleNamespace(request_tokens=11, response_tokens=7),
            )

    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())

    result = await service.generate_response(make_query())

    assert result.prompt_tokens == 11
    assert result.completion_tokens == 7


@pytest.mark.asyncio
async def test_generate_response_preserves_zero_completion_tokens(monkeypatch) -> None:
    service = PydanticAILLMService(
        api_key="test-key", model_name="gemini-test", provider_name="gemini"
    )

    class FakeAgent:
        async def run(self, prompt: str, **kwargs):
            return SimpleNamespace(
                output="",
                usage=lambda: SimpleNamespace(request_tokens=3, response_tokens=0),
            )

    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())

    result = await service.generate_response(make_query())

    assert result.prompt_tokens == 3
    assert result.completion_tokens == 0


@pytest.mark.asyncio
async def test_generate_response_merges_extra_body(monkeypatch) -> None:
    service = PydanticAILLMService(
        api_key="test-key",
        model_name="gemini-test",
        extra_body={"thinking": {"type": "enabled"}, "profile": "default"},
    )
    captured = {}

    class FakeAgent:
        async def run(self, prompt: str, **kwargs):
            captured["model_settings"] = kwargs["model_settings"]
            return SimpleNamespace(output="answer")

    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())
    query = make_query()
    query.extra_body = {"profile": "request"}

    await service.generate_response(query)

    assert captured["model_settings"]["extra_body"] == {
        "thinking": {"type": "enabled"},
        "profile": "request",
    }


@pytest.mark.asyncio
async def test_stream_response_yields_delta_chunks(monkeypatch) -> None:
    service = PydanticAILLMService(
        api_key="test-key", model_name="gemini-test", provider_name="gemini"
    )

    class FakeStreamResult:
        async def stream_text(self, *, delta: bool = False):
            assert delta is True
            yield "Gemini "
            yield "chunk"

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeStreamResult()

        async def __aexit__(self, *_):
            return None

    class FakeAgent:
        def run_stream(self, prompt: str, **kwargs):
            assert prompt == "当前问题"
            assert kwargs["model_settings"] is None
            return FakeStreamContext()

    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())

    chunks = [chunk async for chunk in service.stream_response(make_query())]

    assert chunks == ["Gemini ", "chunk"]


@pytest.mark.asyncio
async def test_generate_response_marks_circuit_failure(monkeypatch) -> None:
    service = PydanticAILLMService(api_key="test-key", model_name="gemini-test")
    calls = {"failure": 0}

    class FakeCircuit:
        async def acquire(self):
            return None

        async def on_success(self):
            return None

        async def on_failure(self):
            calls["failure"] += 1

    class FakeAgent:
        async def run(self, prompt: str, **kwargs):
            raise RuntimeError("provider failed")

    service._circuit = FakeCircuit()
    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())

    with pytest.raises(AppException):
        await service.generate_response(make_query())

    assert calls["failure"] == 1


@pytest.mark.asyncio
async def test_stream_midfailure_marks_circuit_failure_not_success(monkeypatch) -> None:
    """流式中途失败时应只记 failure，不得先记 success（缺陷 2 的回归）。"""
    service = PydanticAILLMService(
        api_key="test-key", model_name="gemini-test", provider_name="gemini"
    )
    events: list[str] = []

    class FakeCircuit:
        async def acquire(self):
            return None

        async def on_success(self):
            events.append("success")

        async def on_failure(self):
            events.append("failure")

    class FakeStreamResult:
        async def stream_text(self, *, delta: bool = False):
            yield "partial"
            raise RuntimeError("stream broke mid-way")

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeStreamResult()

        async def __aexit__(self, *_):
            return None

    class FakeAgent:
        def run_stream(self, prompt: str, **kwargs):
            return FakeStreamContext()

    service._circuit = FakeCircuit()
    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())

    with pytest.raises(AppException):
        async for _ in service.stream_response(make_query()):
            pass

    assert events == ["failure"]


@pytest.mark.asyncio
async def test_stream_success_marks_circuit_success_after_iteration(
    monkeypatch,
) -> None:
    """流式正常读完后才标记成功。"""
    service = PydanticAILLMService(
        api_key="test-key", model_name="gemini-test", provider_name="gemini"
    )
    events: list[str] = []

    class FakeCircuit:
        async def acquire(self):
            return None

        async def on_success(self):
            events.append("success")

        async def on_failure(self):
            events.append("failure")

    class FakeStreamResult:
        async def stream_text(self, *, delta: bool = False):
            yield "ok"

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeStreamResult()

        async def __aexit__(self, *_):
            return None

    class FakeAgent:
        def run_stream(self, prompt: str, **kwargs):
            return FakeStreamContext()

    service._circuit = FakeCircuit()
    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())

    chunks = [chunk async for chunk in service.stream_response(make_query())]

    assert chunks == ["ok"]
    assert events == ["success"]


def test_create_agent_requires_gemini_api_key() -> None:
    service = PydanticAILLMService(api_key="", model_name="gemini-test")

    with pytest.raises(AppException):
        service._create_agent("instructions")


def test_circuit_breaker_config_can_be_injected() -> None:
    service = PydanticAILLMService(
        api_key="test-key",
        model_name="gemini-test",
        circuit_breaker_failure_threshold=9,
        circuit_breaker_cooldown_seconds=11,
    )

    assert service._circuit.failure_threshold == 9
    assert service._circuit.cooldown_seconds == 11


def test_create_agent_enables_pydantic_ai_instrumentation() -> None:
    service = PydanticAILLMService(api_key="test-key", model_name="gemini-test")

    agent = service._create_agent("instructions")

    assert agent.instrument is True
    assert agent.name == "llm"


def test_create_model_supports_google_provider() -> None:
    profile = get_llm_model_config().resolve_profile("gemini")

    model = create_pydantic_ai_model(profile=profile, api_key="test-key")

    assert type(model).__name__ == "GoogleModel"


def test_create_model_supports_openai_compatible_provider() -> None:
    profile = get_llm_model_config().resolve_profile("deepseek-v4-flash")

    model = create_pydantic_ai_model(profile=profile, api_key="test-key")

    assert type(model).__name__ == "OpenAIChatModel"


def test_factory_returns_pydantic_ai_service_for_gemini_provider() -> None:
    service = LLMProviderFactory.create("gemini")

    assert isinstance(service, PydanticAILLMService)


def test_factory_returns_pydantic_ai_service_for_openai_compatible(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    service = LLMProviderFactory.create("openai-compatible")

    assert isinstance(service, PydanticAILLMService)
    assert service.provider_name == "openai-compatible"


def test_factory_deepseek_v4_alias_sets_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.llm.factory.settings.DEEPSEEK_API_KEY",
        "deepseek-key",
    )

    service = LLMProviderFactory.create("deepseek-v4-flash")

    assert isinstance(service, PydanticAILLMService)
    assert service.provider_name == "deepseek"
    assert service.model_name == "deepseek-v4-flash"


def test_factory_expands_multiple_keys_into_routing_service(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key-a,deepseek-key-b")

    service = LLMProviderFactory.create("deepseek")

    assert isinstance(service, LLMRoutingService)
    assert len(service.candidates) == 2
    first = service.candidates[0].service
    second = service.candidates[1].service
    assert isinstance(first, PydanticAILLMService)
    assert isinstance(second, PydanticAILLMService)
    assert first.api_key == "deepseek-key-a"
    assert second.api_key == "deepseek-key-b"
    assert first.max_retries == 0


def test_factory_returns_routing_service_for_model_route(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    service = LLMProviderFactory.create("auto")

    assert isinstance(service, LLMRoutingService)
    assert [candidate.label for candidate in service.candidates] == [
        "deepseek/deepseek-v4-flash#key1",
        "gemini/gemini-2.5-flash#key1",
    ]
