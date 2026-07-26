"""Shared test doubles for worker generation workflow tests.

职责：为 worker 生成流程的拆分测试文件提供 Redis/LLM/RAG 替身与断言辅助;边界：纯内存替身,不连接真实 Redis/LLM;副作用:无。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from unittest.mock import AsyncMock

from backend.application.chat.stream_events import decode_stream_event
from backend.application.chat.worker_rag_orchestrator import PreparedGenerationContext
from backend.models.schemas.chat.dto import LLMQueryDTO, LLMResultDTO
from backend.models.schemas.chat.payloads import GenerationPayload
from backend.services.rag_planning_service import RAGExecutionPlan


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.set_calls: list[tuple[str, str, int]] = []
        self.deleted: list[str] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    async def set(self, key: str, value: str, ex: int) -> None:
        self.set_calls.append((key, value, ex))

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


class FakeRedisClient:
    def __init__(self, *connections: FakeRedis) -> None:
        self.connections = list(connections)
        self.init_calls: int = 0

    async def init(self) -> FakeRedis:
        self.init_calls += 1
        if len(self.connections) > 1:
            return self.connections.pop(0)
        return self.connections[0]


class RecordingConcurrencySlot:
    def __init__(self, calls: list[dict], attributes: dict | None) -> None:
        self.calls = calls
        self.attributes = attributes or {}

    async def __aenter__(self) -> None:
        self.calls.append(self.attributes)

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def install_llm_slot_recorder(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_llm_concurrency_slot(
        attributes: dict | None = None,
    ) -> RecordingConcurrencySlot:
        return RecordingConcurrencySlot(calls, attributes)

    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.llm_concurrency_slot",
        fake_llm_concurrency_slot,
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_rag_orchestrator.llm_concurrency_slot",
        fake_llm_concurrency_slot,
    )
    return calls


class StreamingLLM:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(
        self,
        chunks: list[str],
        error: Exception | None = None,
        rerank_content: str | None = None,
    ) -> None:
        self.chunks = chunks
        self.error = error
        self.stream_queries: list[LLMQueryDTO] = []
        self.generate_response = AsyncMock(
            return_value=LLMResultDTO(
                content=rerank_content or '{"rankings": [{"index": 1, "score": 10}]}',
            )
        )

    async def stream_response(self, query: LLMQueryDTO) -> AsyncIterator[str]:
        self.stream_queries.append(query)
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error


class NonStreamingLLM:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, result: LLMResultDTO) -> None:
        self.generate_response = AsyncMock(return_value=result)


class RecordingRAGService:
    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits
        self.retrieve = AsyncMock(return_value=hits)
        self.retrieve_fulltext = AsyncMock(return_value=hits)
        self.retrieve_hybrid = AsyncMock(return_value=hits)
        self.rerank = AsyncMock(return_value=hits)


class RecordingRAGPlanner:
    def __init__(
        self,
        plan: RAGExecutionPlan | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response_plan = plan
        self.error = error
        self.plan_calls: list[dict] = []

    async def plan(self, **kwargs) -> RAGExecutionPlan:
        self.plan_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response_plan is not None
        return self.response_plan


class StaticRAGOrchestrator:
    def __init__(self, prepared_context: PreparedGenerationContext) -> None:
        self.prepared_context = prepared_context

    async def prepare_context(
        self,
        payload: GenerationPayload,
        *,
        on_step=None,
    ) -> PreparedGenerationContext:
        return self.prepared_context


def without_step_events(
    published: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Drop trace step events when asserting chunk/done Redis publish order."""
    return [
        item for item in published if decode_stream_event(item[1]).get("type") != "step"
    ]


def make_rerank_impl(
    rankings: list[tuple[int, float]],
) -> Callable[[str, list[dict], int | None], Awaitable[list[dict]]]:
    """Apply native-style rerank scores to candidates."""

    async def _rerank_impl(
        query_text: str, candidates: list[dict], top_k: int | None = None
    ) -> list[dict]:
        from backend.services.rag_service import RAGService

        return RAGService.apply_rankings(
            candidates=candidates,
            rankings=rankings,
            limit=top_k or 4,
            score_kind="bifrost_rerank",
            index_base=0,
        )

    return _rerank_impl
