"""External context retrieval providers.

职责：把开放 Web 等外部上下文检索结果标准化为 RAG 可消费的 chunk-like dict。
边界：本模块不组装 Prompt、不做证据策略判断；调用失败时返回空结果。
"""

import logging
import uuid
from typing import Any

import httpx
from pydantic import BaseModel, Field

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractExternalContextProvider
from backend.core.circuit_breaker import CircuitBreaker
from backend.core.exceptions import AppException
from backend.observability.trace_utils import set_span_attributes, trace_span

logger = logging.getLogger(__name__)


class ExternalContextChunk(BaseModel):
    """Provider-neutral external context chunk."""

    id: str
    content: str
    source_type: str = "web"
    provider: str
    title: str | None = None
    url: str | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    meta_info: dict[str, Any] = Field(default_factory=dict)

    def to_rag_chunk(self, *, chunk_index: int) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "source_type": self.source_type,
            "provider": self.provider,
            "title": self.title,
            "url": self.url,
            "filename": self.title or self.url or self.provider,
            "file_id": self.url,
            "message_id": None,
            "chunk_index": chunk_index,
            "meta_info": self.meta_info,
            "distance": max(0.0, 1.0 - self.score),
            "score": self.score,
            "retrieval_mode": "external",
            "score_kind": f"{self.provider}_score",
            "raw_score": self.score,
            "evidence_score": self.score,
            "matched_by": [self.source_type],
        }


class TavilyExternalContextProvider(AbstractExternalContextProvider):
    """Tavily-backed Web context provider."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        circuit_breaker_failure_threshold: int | None = None,
        circuit_breaker_cooldown_seconds: int | None = None,
    ) -> None:
        self._api_key = api_key or ai_settings.TAVILY_API_KEY
        self._base_url = (base_url or ai_settings.TAVILY_BASE_URL).rstrip("/")
        self._timeout_seconds = (
            timeout_seconds or ai_settings.EXTERNAL_CONTEXT_TIMEOUT_SECONDS
        )
        self._client: httpx.AsyncClient | None = None
        self._circuit = CircuitBreaker(
            name="external_context:tavily",
            failure_threshold=(
                circuit_breaker_failure_threshold
                or ai_settings.EXTERNAL_CONTEXT_CIRCUIT_BREAKER_FAILURE_THRESHOLD
            ),
            cooldown_seconds=(
                circuit_breaker_cooldown_seconds
                or ai_settings.EXTERNAL_CONTEXT_CIRCUIT_BREAKER_COOLDOWN_SECONDS
            ),
        )

    @property
    def provider_name(self) -> str:
        return "tavily"

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search(self, *, query_text: str, top_k: int) -> list[Any]:
        if not self._api_key or not query_text.strip() or top_k <= 0:
            return []

        # Fast-fail when the circuit breaker is OPEN: skip the external call and degrade to empty results.
        try:
            await self._circuit.acquire()
        except AppException as exc:
            logger.warning("Tavily 外部上下文检索熔断中，降级为空结果: %s", exc)
            return []

        try:
            with trace_span(
                "external_context.tavily.search",
                {
                    "external_context.provider": self.provider_name,
                    "external_context.top_k": top_k,
                    "external_context.query.char_count": len(query_text),
                },
            ) as span:
                if self._client is None:
                    self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
                response = await self._client.post(
                    f"{self._base_url}/search",
                    json={
                        "api_key": self._api_key,
                        "query": query_text,
                        "max_results": top_k,
                        "include_answer": False,
                        "include_raw_content": False,
                    },
                )
                response.raise_for_status()
                chunks = self._parse_response(response.json(), top_k=top_k)
                set_span_attributes(span, {"external_context.hit_count": len(chunks)})
        except Exception as exc:
            await self._circuit.on_failure()
            logger.warning("Tavily 外部上下文检索失败，降级为空结果: %s", exc)
            return []
        await self._circuit.on_success()
        return chunks

    def _parse_response(
        self,
        payload: dict[str, Any],
        *,
        top_k: int,
    ) -> list[ExternalContextChunk]:
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            return []

        chunks: list[ExternalContextChunk] = []
        for index, raw in enumerate(raw_results[:top_k]):
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("content") or raw.get("snippet") or "").strip()
            if not content:
                continue
            title = str(raw.get("title") or "").strip() or None
            url = str(raw.get("url") or "").strip() or None
            score = raw.get("score")
            normalized_score = float(score) if isinstance(score, (int, float)) else 0.5
            normalized_score = max(0.0, min(normalized_score, 1.0))
            id_name = url or f"tavily:{index}"
            chunks.append(
                ExternalContextChunk(
                    id=f"web:{uuid.uuid5(uuid.NAMESPACE_URL, id_name).hex}",
                    content=content,
                    provider=self.provider_name,
                    title=title,
                    url=url,
                    score=normalized_score,
                    meta_info={
                        "source_url": url,
                        "source_title": title,
                        "provider": self.provider_name,
                    },
                )
            )
        return chunks


def create_external_context_provider(
    *,
    always_create: bool = False,
) -> AbstractExternalContextProvider | None:
    """Create the configured external context provider."""
    if ai_settings.EXTERNAL_CONTEXT_PROVIDER == "tavily":
        provider = TavilyExternalContextProvider()
        if not provider._api_key:
            return None
        return provider
    if ai_settings.EXTERNAL_CONTEXT_PROVIDER:
        logger.warning(
            "未知外部上下文 provider: %s", ai_settings.EXTERNAL_CONTEXT_PROVIDER
        )
    return None
