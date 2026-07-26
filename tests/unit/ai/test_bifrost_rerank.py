"""Bifrost rerank provider unit tests.

职责：验证 Bifrost /v1/rerank 请求构造和响应解析；边界：替换网络调用，不访问真实网关；副作用：无。
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from backend.ai.providers.rerank.bifrost_rerank import BifrostRerankService
from backend.core.exceptions import AppException, app_service_error


def _real_service() -> BifrostRerankService:
    return BifrostRerankService(
        base_url="http://bifrost:8080/v1",
        api_key="sk-bf-test",
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


class FakeBifrostRerankService(BifrostRerankService):
    def __init__(self, response: dict) -> None:
        super().__init__(
            base_url="http://bifrost:8080/v1",
            api_key="sk-bf-test",
            model_name="qwen3-rerank",
        )
        self.payload: dict | None = None
        self.response = response

    def _post_rerank(self, payload: dict) -> dict:
        self.payload = payload
        return self.response


async def test_bifrost_rerank_constructs_request_and_parses_results() -> None:
    service = FakeBifrostRerankService(
        {
            "results": [
                {"index": 1, "relevance_score": 0.91},
                {"index": 0, "relevance_score": 0.32},
            ],
            "extra_fields": {"provider": "cohere"},
        }
    )

    result = await service.rerank(
        query_text="gateway observability",
        documents=["Bifrost exposes metrics.", "Bifrost reranks documents."],
        top_k=2,
    )

    assert result == [(1, 0.91), (0, 0.32)]
    assert service.payload == {
        "model": "qwen3-rerank",
        "query": "gateway observability",
        "top_n": 2,
        "documents": [
            {"id": "0", "text": "Bifrost exposes metrics."},
            {"id": "1", "text": "Bifrost reranks documents."},
        ],
    }


async def test_bifrost_rerank_returns_empty_for_empty_inputs() -> None:
    service = FakeBifrostRerankService({"results": []})

    assert await service.rerank(query_text="", documents=["doc"], top_k=2) == []
    assert await service.rerank(query_text="query", documents=[], top_k=2) == []
    assert await service.rerank(query_text="query", documents=["doc"], top_k=0) == []


async def test_bifrost_rerank_rejects_invalid_response() -> None:
    service = FakeBifrostRerankService({"results": []})

    with pytest.raises(AppException, match="没有有效排序结果"):
        await service.rerank(query_text="query", documents=["doc"], top_k=1)


async def test_bifrost_rerank_returns_empty_when_results_missing_valid_items() -> None:
    service = FakeBifrostRerankService(
        {"results": [{"index": None, "relevance_score": 0.5}]}
    )

    with pytest.raises(AppException, match="没有有效排序结果"):
        await service.rerank(query_text="query", documents=["doc"], top_k=1)


async def test_bifrost_rerank_rejects_whitespace_only_document() -> None:
    service = FakeBifrostRerankService({"results": []})

    with pytest.raises(AppException, match="Bifrost rerank 文档不能为空"):
        await service.rerank(query_text="query", documents=["   "], top_k=1)


# _post_rerank error paths


def test_post_rerank_raises_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _real_service()

    def _raise_http_error(*args: object, **kwargs: object) -> None:
        fp = io.BytesIO(b"gateway error")
        raise urllib.error.HTTPError(
            url="http://bifrost:8080/v1/rerank",
            code=502,
            msg="Bad Gateway",
            hdrs={},
            fp=fp,
        )

    monkeypatch.setattr(
        "backend.ai.providers.rerank.bifrost_rerank.urllib.request.urlopen",
        _raise_http_error,
    )

    with pytest.raises(AppException) as exc_info:
        service._post_rerank({"model": "test"})

    assert exc_info.value.code == "BIFROST_RERANK_HTTP_ERROR"
    assert exc_info.value.details["status_code"] == 502


def test_post_rerank_raises_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _real_service()

    monkeypatch.setattr(
        "backend.ai.providers.rerank.bifrost_rerank.urllib.request.urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("connection refused")),
    )

    with pytest.raises(AppException) as exc_info:
        service._post_rerank({"model": "test"})

    assert exc_info.value.code == "BIFROST_RERANK_NETWORK_ERROR"


def test_post_rerank_raises_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _real_service()
    monkeypatch.setattr(
        "backend.ai.providers.rerank.bifrost_rerank.urllib.request.urlopen",
        lambda *a, **kw: _FakeResponse(b"not json at all"),
    )

    with pytest.raises(AppException) as exc_info:
        service._post_rerank({"model": "test"})

    assert exc_info.value.code == "BIFROST_RERANK_INVALID_JSON"


def test_post_rerank_raises_invalid_response_for_non_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _real_service()
    monkeypatch.setattr(
        "backend.ai.providers.rerank.bifrost_rerank.urllib.request.urlopen",
        lambda *a, **kw: _FakeResponse(json.dumps([1, 2, 3]).encode()),
    )

    with pytest.raises(AppException) as exc_info:
        service._post_rerank({"model": "test"})

    assert exc_info.value.code == "BIFROST_RERANK_INVALID_RESPONSE"


def test_parse_rankings_raises_missing_results() -> None:
    with pytest.raises(AppException) as exc_info:
        BifrostRerankService._parse_rankings({"no_results_key": []})

    assert exc_info.value.code == "BIFROST_RERANK_MISSING_RESULTS"


# 断路器（与 rag_service 降级叠加：熔断快速失败 + 降级兜底）


class FailingBifrostRerankService(BifrostRerankService):
    """每次 _post_rerank 都抛下游错误，用于驱动断路器。"""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            base_url="http://bifrost:8080/v1",
            api_key="sk-bf-test",
            model_name="qwen3-rerank",
            **kwargs,
        )
        self.calls = 0

    def _post_rerank(self, payload: dict) -> dict:
        self.calls += 1
        raise app_service_error(
            "Bifrost rerank API 调用失败",
            code="BIFROST_RERANK_HTTP_ERROR",
            details={"status_code": 502},
        )


async def test_rerank_circuit_breaker_opens_after_threshold_failures() -> None:
    service = FailingBifrostRerankService(
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )

    for _ in range(2):
        with pytest.raises(AppException) as exc_info:
            await service.rerank(query_text="q", documents=["doc"], top_k=1)
        assert exc_info.value.code == "BIFROST_RERANK_HTTP_ERROR"

    assert service.calls == 2

    # 达到阈值后断路器打开：快速失败且不再触达下游
    with pytest.raises(AppException) as exc_info:
        await service.rerank(query_text="q", documents=["doc"], top_k=1)
    assert exc_info.value.code == "CIRCUIT_BREAKER_OPEN"
    assert service.calls == 2


async def test_rerank_circuit_breaker_ignores_validation_errors() -> None:
    service = FailingBifrostRerankService(
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )

    # 校验错误（空文档）发生在断路器之外，多次也不应累计失败
    for _ in range(5):
        with pytest.raises(AppException, match="文档不能为空"):
            await service.rerank(query_text="q", documents=["   "], top_k=1)

    # 断路器仍闭合：放行到下游（此处下游返回 HTTP 错误，证明 acquire 未拦截）
    with pytest.raises(AppException) as exc_info:
        await service.rerank(query_text="q", documents=["doc"], top_k=1)
    assert exc_info.value.code == "BIFROST_RERANK_HTTP_ERROR"
    assert service.calls == 1
