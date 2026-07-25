"""Bifrost rerank provider.

职责：调用 Bifrost OpenAI-compatible gateway 的 /v1/rerank 接口。
边界：只解析 rerank 响应，不执行检索、不组装 Prompt。
失败处理：调用方负责把异常降级为候选原始排序。
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractRerankService
from backend.core.circuit_breaker import CircuitBreaker
from backend.core.exceptions import app_service_error
from backend.observability.trace_utils import (
    build_llm_span_attributes,
    set_span_attributes,
    trace_span,
)

logger = logging.getLogger(__name__)


class BifrostRerankService(AbstractRerankService):
    """Bifrost /v1/rerank client."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout_seconds: int = 15,
        circuit_breaker_failure_threshold: int | None = None,
        circuit_breaker_cooldown_seconds: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self._circuit = CircuitBreaker(
            name="rerank:bifrost",
            failure_threshold=(
                circuit_breaker_failure_threshold
                or ai_settings.RAG_RERANK_CIRCUIT_BREAKER_FAILURE_THRESHOLD
            ),
            cooldown_seconds=(
                circuit_breaker_cooldown_seconds
                or ai_settings.RAG_RERANK_CIRCUIT_BREAKER_COOLDOWN_SECONDS
            ),
        )

    async def rerank(
        self,
        *,
        query_text: str,
        documents: list[str],
        top_k: int,
    ) -> list[tuple[int, float]]:
        payloads = list(documents)
        if not query_text.strip() or not payloads or top_k <= 0:
            return []
        if any(not str(doc).strip() for doc in payloads):
            raise app_service_error(
                "Bifrost rerank 文档不能为空",
                code="BIFROST_RERANK_EMPTY_DOCUMENT",
            )

        # External calls after validation are circuit-breaker protected: fast-fail with
        # CIRCUIT_BREAKER_OPEN when OPEN; rag_service degrades to raw candidate order.
        await self._circuit.acquire()
        try:
            with trace_span(
                "rerank.bifrost",
                {
                    **build_llm_span_attributes(
                        provider="bifrost",
                        model=self.model_name,
                        operation="rerank",
                    ),
                    "rerank.input.count": len(payloads),
                    "rerank.top_k": top_k,
                },
            ) as span:
                response = await asyncio.to_thread(
                    self._post_rerank,
                    {
                        "model": self.model_name,
                        "query": query_text,
                        "top_n": top_k,
                        "documents": [
                            {"id": str(index), "text": document}
                            for index, document in enumerate(payloads)
                        ],
                    },
                )
                rankings = self._parse_rankings(response)
                set_span_attributes(
                    span,
                    {
                        "rerank.output.count": len(rankings),
                        "rerank.provider": response.get("extra_fields", {}).get(
                            "provider"
                        ),
                    },
                )
        except Exception:
            await self._circuit.on_failure()
            raise
        await self._circuit.on_success()
        return rankings

    def _post_rerank(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/rerank"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - configured gateway URL
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "x-bf-vk": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - configured gateway URL
                request,
                timeout=self.timeout_seconds,
            ) as response:
                data = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            logger.warning(
                "Bifrost rerank API HTTP failure",
                extra={
                    "event": "rag_rerank_provider_failed",
                    "error_code": "BIFROST_RERANK_HTTP_ERROR",
                    "status_code": exc.code,
                    "error_type": type(exc).__name__,
                },
            )
            raise app_service_error(
                "Bifrost rerank API 调用失败",
                code="BIFROST_RERANK_HTTP_ERROR",
                details={"status_code": exc.code},
            ) from None
        except OSError as exc:
            raise app_service_error(
                "Bifrost rerank API 网络错误",
                code="BIFROST_RERANK_NETWORK_ERROR",
                details={"error_type": type(exc).__name__},
            ) from None

        try:
            decoded = json.loads(data)
        except json.JSONDecodeError:
            raise app_service_error(
                "Bifrost rerank API 返回非法 JSON",
                code="BIFROST_RERANK_INVALID_JSON",
            ) from None
        if not isinstance(decoded, dict):
            raise app_service_error(
                "Bifrost rerank API 返回格式错误",
                code="BIFROST_RERANK_INVALID_RESPONSE",
            )
        return decoded

    @staticmethod
    def _parse_rankings(response: dict[str, Any]) -> list[tuple[int, float]]:
        results = response.get("results")
        if not isinstance(results, list):
            raise app_service_error(
                "Bifrost rerank API 缺少 results",
                code="BIFROST_RERANK_MISSING_RESULTS",
            )

        rankings: list[tuple[int, float]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            score = item.get("relevance_score")
            if isinstance(index, int) and isinstance(score, int | float):
                rankings.append((index, float(score)))
        if not rankings:
            raise app_service_error(
                "Bifrost rerank API 没有有效排序结果",
                code="BIFROST_RERANK_EMPTY_RESULTS",
            )
        return rankings
