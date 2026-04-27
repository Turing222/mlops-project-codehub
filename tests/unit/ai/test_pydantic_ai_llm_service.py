import uuid
from types import SimpleNamespace

import pytest

from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.ai.providers.llm.llm_service import LLMService
from backend.ai.providers.llm.pydantic_ai_service import PydanticAILLMService
from backend.ai.providers.llm.routing_service import LLMRoutingService
from backend.core.exceptions import ServiceError
from backend.models.schemas.chat_schema import LLMQueryDTO


def make_query(messages: list[dict] | None = None) -> LLMQueryDTO:
    return LLMQueryDTO(
        session_id=uuid.uuid4(),
        query_text="当前问题",
        conversation_history=messages or [],
    )


def test_build_agent_input_splits_system_history_and_current_user():
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
async def test_generate_response_uses_pydantic_agent(monkeypatch):
    service = PydanticAILLMService(api_key="test-key", model_name="gemini-test")
    captured = {}

    class FakeAgent:
        async def run(self, prompt: str):
            captured["prompt"] = prompt
            return SimpleNamespace(output="Gemini answer")

    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())

    result = await service.generate_response(make_query())

    assert captured["prompt"] == "当前问题"
    assert result.content == "Gemini answer"
    assert result.success is True


@pytest.mark.asyncio
async def test_stream_response_yields_delta_chunks(monkeypatch):
    service = PydanticAILLMService(api_key="test-key", model_name="gemini-test")

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
        def run_stream(self, prompt: str):
            assert prompt == "当前问题"
            return FakeStreamContext()

    monkeypatch.setattr(service, "_create_agent", lambda instructions: FakeAgent())

    chunks = [chunk async for chunk in service.stream_response(make_query())]

    assert chunks == ["Gemini ", "chunk"]


def test_create_agent_requires_gemini_api_key():
    service = PydanticAILLMService(api_key="", model_name="gemini-test")

    with pytest.raises(ServiceError):
        service._create_agent("instructions")


def test_create_agent_enables_pydantic_ai_instrumentation():
    service = PydanticAILLMService(api_key="test-key", model_name="gemini-test")

    agent = service._create_agent("instructions")

    assert agent.instrument is True
    assert agent.name == "gemini_llm"


def test_factory_returns_pydantic_ai_service_for_gemini_provider():
    service = LLMProviderFactory.create("gemini")

    assert isinstance(service, PydanticAILLMService)


def test_factory_returns_openai_compatible_service_for_deepseek(monkeypatch):
    monkeypatch.setattr(
        "backend.ai.providers.llm.factory.settings.DEEPSEEK_API_KEY",
        "deepseek-key",
    )

    service = LLMProviderFactory.create("deepseek")

    assert isinstance(service, LLMService)
    assert service.provider_name == "deepseek"
    assert service.base_url == "https://api.deepseek.com"
    assert service.api_key == "deepseek-key"
    assert service.model_name == "deepseek-chat"


def test_factory_deepseek_reasoner_alias_sets_model(monkeypatch):
    monkeypatch.setattr(
        "backend.ai.providers.llm.factory.settings.DEEPSEEK_API_KEY",
        "deepseek-key",
    )

    service = LLMProviderFactory.create("deepseek-reasoner")

    assert isinstance(service, LLMService)
    assert service.provider_name == "deepseek"
    assert service.model_name == "deepseek-reasoner"


def test_factory_deepseek_v4_alias_sets_model(monkeypatch):
    monkeypatch.setattr(
        "backend.ai.providers.llm.factory.settings.DEEPSEEK_API_KEY",
        "deepseek-key",
    )

    service = LLMProviderFactory.create("deepseek-v4-flash")

    assert isinstance(service, LLMService)
    assert service.provider_name == "deepseek"
    assert service.model_name == "deepseek-v4-flash"


def test_factory_expands_multiple_keys_into_routing_service(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key-a,deepseek-key-b")

    service = LLMProviderFactory.create("deepseek")

    assert isinstance(service, LLMRoutingService)
    assert len(service.candidates) == 2
    first = service.candidates[0].service
    second = service.candidates[1].service
    assert isinstance(first, LLMService)
    assert isinstance(second, LLMService)
    assert first.api_key == "deepseek-key-a"
    assert second.api_key == "deepseek-key-b"
    assert first.max_retries == 0


def test_factory_returns_routing_service_for_model_route(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    service = LLMProviderFactory.create("auto")

    assert isinstance(service, LLMRoutingService)
    assert [candidate.label for candidate in service.candidates] == [
        "deepseek/deepseek-chat#key1",
        "deepseek/deepseek-v4-flash#key1",
        "gemini/gemini-2.5-flash#key1",
    ]
