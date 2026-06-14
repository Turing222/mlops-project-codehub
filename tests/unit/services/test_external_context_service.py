"""External context provider unit tests.

职责：验证外部上下文 provider 的结果标准化与配置降级；边界：不连接真实 Tavily API。
"""

from unittest.mock import patch

import httpx
import pytest

from backend.services.external_context_service import (
    TavilyExternalContextProvider,
    create_external_context_provider,
)


def test_tavily_parse_response_normalizes_chunks() -> None:
    provider = TavilyExternalContextProvider(api_key="key")

    chunks = provider._parse_response(
        {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com",
                    "content": "Fresh context",
                    "score": 0.8,
                }
            ]
        },
        top_k=3,
    )

    assert len(chunks) == 1
    rag_chunk = chunks[0].to_rag_chunk(chunk_index=0)
    assert rag_chunk["source_type"] == "web"
    assert rag_chunk["provider"] == "tavily"
    assert rag_chunk["url"] == "https://example.com"
    assert rag_chunk["evidence_score"] == 0.8


def test_create_external_context_provider_returns_none_when_no_provider_configured() -> (
    None
):
    with patch(
        "backend.services.external_context_service.ai_settings.EXTERNAL_CONTEXT_PROVIDER",
        None,
    ):
        assert create_external_context_provider() is None


def test_create_external_context_provider_returns_none_when_no_api_key() -> None:
    with (
        patch(
            "backend.services.external_context_service.ai_settings.EXTERNAL_CONTEXT_PROVIDER",
            "tavily",
        ),
        patch(
            "backend.services.external_context_service.ai_settings.TAVILY_API_KEY",
            None,
        ),
    ):
        assert create_external_context_provider() is None


def test_create_external_context_provider_returns_provider_when_configured() -> None:
    with (
        patch(
            "backend.services.external_context_service.ai_settings.EXTERNAL_CONTEXT_PROVIDER",
            "tavily",
        ),
        patch(
            "backend.services.external_context_service.ai_settings.TAVILY_API_KEY",
            "test-key",
        ),
    ):
        provider = create_external_context_provider()
        assert provider is not None


# ── 断路器（与既有「降级为空结果」叠加：熔断快速失败 + 降级兜底） ──────


class _FakeFailingClient:
    """模拟 Tavily HTTP 客户端持续失败。"""

    def __init__(self) -> None:
        self.calls = 0

    async def post(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        raise httpx.ConnectError("tavily down")

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_tavily_circuit_breaker_opens_after_threshold_failures() -> None:
    provider = TavilyExternalContextProvider(
        api_key="key",
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )
    fake = _FakeFailingClient()
    provider._client = fake  # type: ignore[assignment]

    for _ in range(2):
        assert await provider.search(query_text="q", top_k=3) == []
    assert fake.calls == 2

    # 阈值后断路器打开：快速失败降级为空，且不再发起 HTTP 调用
    assert await provider.search(query_text="q", top_k=3) == []
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_tavily_circuit_breaker_ignores_validation_errors() -> None:
    provider = TavilyExternalContextProvider(
        api_key="key",
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )
    fake = _FakeFailingClient()
    provider._client = fake  # type: ignore[assignment]

    # 空查询在断路器之外早返回，多次也不应累计失败
    for _ in range(5):
        assert await provider.search(query_text="   ", top_k=3) == []
    assert fake.calls == 0

    # 断路器仍闭合：真实查询会放行到下游（此处下游失败，证明 acquire 未拦截）
    assert await provider.search(query_text="q", top_k=3) == []
    assert fake.calls == 1
