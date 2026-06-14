"""DashScope rerank provider unit tests."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from backend.ai.providers.rerank.dashscope_rerank import DashScopeRerankService
from backend.core.exceptions import AppException, app_service_error


def _real_service() -> DashScopeRerankService:
    return DashScopeRerankService(
        base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
        api_key="sk-dashscope-test",
        model_name="qwen3-rerank",
    )


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class FakeDashScopeRerankService(DashScopeRerankService):
    def __init__(self, response: dict) -> None:
        super().__init__(
            base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            api_key="sk-dashscope-test",
            model_name="qwen3-rerank",
        )
        self.payload: dict | None = None
        self.response = response

    def _post_rerank(self, payload: dict) -> dict:
        self.payload = payload
        return self.response


async def test_dashscope_rerank_constructs_request_and_parses_results() -> None:
    service = FakeDashScopeRerankService(
        {
            "results": [
                {"index": 1, "relevance_score": 0.91},
                {"index": 0, "relevance_score": 0.32},
            ]
        }
    )

    result = await service.rerank(
        query_text="gateway observability",
        documents=["Bifrost exposes metrics.", "DashScope reranks documents."],
        top_k=2,
    )

    assert result == [(1, 0.91), (0, 0.32)]
    assert service.payload == {
        "model": "qwen3-rerank",
        "query": "gateway observability",
        "top_n": 2,
        "documents": [
            "Bifrost exposes metrics.",
            "DashScope reranks documents.",
        ],
    }


def test_post_rerank_uses_reranks_endpoint_and_string_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _real_service()
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse(b'{"results":[{"index":0,"relevance_score":0.8}]}')

    monkeypatch.setattr(
        "backend.ai.providers.rerank.dashscope_rerank.urllib.request.urlopen",
        _fake_urlopen,
    )

    service._post_rerank(
        {
            "model": "qwen3-rerank",
            "query": "query",
            "top_n": 1,
            "documents": ["doc"],
        }
    )

    assert captured["url"] == "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"
    assert captured["body"] == {
        "model": "qwen3-rerank",
        "query": "query",
        "top_n": 1,
        "documents": ["doc"],
    }


async def test_dashscope_rerank_returns_empty_for_empty_inputs() -> None:
    service = FakeDashScopeRerankService({"results": []})

    assert await service.rerank(query_text="", documents=["doc"], top_k=2) == []
    assert await service.rerank(query_text="query", documents=[], top_k=2) == []
    assert await service.rerank(query_text="query", documents=["doc"], top_k=0) == []


async def test_dashscope_rerank_rejects_whitespace_only_document() -> None:
    service = FakeDashScopeRerankService({"results": []})

    with pytest.raises(AppException, match="文档不能为空"):
        await service.rerank(query_text="query", documents=["   "], top_k=1)


def test_post_rerank_raises_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _real_service()

    def _raise_http_error(*args: object, **kwargs: object) -> None:
        fp = io.BytesIO(b"dashscope error")
        raise urllib.error.HTTPError(
            url="https://dashscope.aliyuncs.com/compatible-api/v1/reranks",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=fp,
        )

    monkeypatch.setattr(
        "backend.ai.providers.rerank.dashscope_rerank.urllib.request.urlopen",
        _raise_http_error,
    )

    with pytest.raises(AppException) as exc_info:
        service._post_rerank({"model": "test"})

    assert exc_info.value.code == "DASHSCOPE_RERANK_HTTP_ERROR"
    assert exc_info.value.details["status_code"] == 400
    assert exc_info.value.details["body"] == "dashscope error"


def test_post_rerank_raises_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _real_service()
    monkeypatch.setattr(
        "backend.ai.providers.rerank.dashscope_rerank.urllib.request.urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("connection refused")),
    )

    with pytest.raises(AppException) as exc_info:
        service._post_rerank({"model": "test"})

    assert exc_info.value.code == "DASHSCOPE_RERANK_NETWORK_ERROR"


def test_post_rerank_raises_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _real_service()
    monkeypatch.setattr(
        "backend.ai.providers.rerank.dashscope_rerank.urllib.request.urlopen",
        lambda *a, **kw: _FakeResponse(b"not json at all"),
    )

    with pytest.raises(AppException) as exc_info:
        service._post_rerank({"model": "test"})

    assert exc_info.value.code == "DASHSCOPE_RERANK_INVALID_JSON"


def test_parse_rankings_raises_missing_results() -> None:
    with pytest.raises(AppException) as exc_info:
        DashScopeRerankService._parse_rankings({"no_results_key": []})

    assert exc_info.value.code == "DASHSCOPE_RERANK_MISSING_RESULTS"


def test_parse_rankings_raises_empty_results() -> None:
    with pytest.raises(AppException) as exc_info:
        DashScopeRerankService._parse_rankings(
            {"results": [{"index": None, "relevance_score": 0.5}]}
        )

    assert exc_info.value.code == "DASHSCOPE_RERANK_EMPTY_RESULTS"


# ── 断路器（确认 rerank 熔断模板在第二个 provider 同样生效） ──────────


class FailingDashScopeRerankService(DashScopeRerankService):
    """每次 _post_rerank 都抛下游错误，用于驱动断路器。"""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            api_key="sk-dashscope-test",
            model_name="qwen3-rerank",
            **kwargs,
        )
        self.calls = 0

    def _post_rerank(self, payload: dict) -> dict:
        self.calls += 1
        raise app_service_error(
            "DashScope rerank API 网络错误",
            code="DASHSCOPE_RERANK_NETWORK_ERROR",
        )


async def test_rerank_circuit_breaker_opens_after_threshold_failures() -> None:
    service = FailingDashScopeRerankService(
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )

    for _ in range(2):
        with pytest.raises(AppException) as exc_info:
            await service.rerank(query_text="q", documents=["doc"], top_k=1)
        assert exc_info.value.code == "DASHSCOPE_RERANK_NETWORK_ERROR"

    assert service.calls == 2

    with pytest.raises(AppException) as exc_info:
        await service.rerank(query_text="q", documents=["doc"], top_k=1)
    assert exc_info.value.code == "CIRCUIT_BREAKER_OPEN"
    assert service.calls == 2
