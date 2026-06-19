"""Eval pipeline review-fix unit tests.

职责：验证 planner scoring、planner skip retrieval、API token refresh 和 Ragas 行数保护。
边界：使用 fake 服务，不访问数据库、HTTP 服务或真实 LLM；副作用：无。
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

from evals.common import build_rag_service
from evals.eval_api_answer import run_ragas
from evals.eval_rag_planner import _score_plan
from evals.eval_retrieval import _run_one_mode


class FakePlan(BaseModel):
    should_use_rag: object
    retrieval_mode: str = "hybrid"
    top_k: int = 4
    use_rerank: object = False
    candidate_count: int = 20
    rerank_top_k: int = 4
    reason: str = ""


class FakePlanner:
    async def plan(self, **kwargs: object) -> FakePlan:
        return FakePlan(should_use_rag=False)


class FakeRAGService:
    def __init__(self) -> None:
        self.retrieve_calls = 0

    async def retrieve(self, **kwargs: object) -> list[dict]:
        self.retrieve_calls += 1
        return [{"id": "chunk-1", "content": "hello", "score": 1.0}]


class FakeSample:
    id = "case-1"
    category = "fact"
    query = "hello"
    kb_id = None
    retrieval_mode = None
    expected_chunk_ids: list[str] = []
    expected_keywords = ["hello"]
    must_refuse = False


def test_score_plan_does_not_coerce_truthy_bool_values() -> None:
    plan = FakePlan(should_use_rag="yes", use_rerank=1)

    scores = _score_plan(
        plan,
        {
            "should_use_rag": True,
            "retrieval_mode": "hybrid",
            "use_rerank": True,
        },
    )

    assert scores["should_use_rag_match"] == 0.0
    assert scores["rerank_decision_match"] == 0.0
    assert scores["retrieval_mode_match"] == 1.0
    assert scores["planner_match"] == 0.0


def test_retrieval_build_rag_service_injects_reranker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeConstructedRAGService:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "backend.services.rag_service.RAGService", FakeConstructedRAGService
    )
    reranker = object()

    service = build_rag_service(
        embedder=object(),
        vector_index_service=object(),  # type: ignore[arg-type]
        top_k=4,
        reranker=reranker,
        rerank_candidate_count=20,
        rerank_top_k=4,
    )

    assert isinstance(service, FakeConstructedRAGService)
    assert captured["reranker"] is reranker


async def test_retrieval_planner_skip_does_not_call_retrieve() -> None:
    rag_service = FakeRAGService()

    rows, summary = await _run_one_mode(
        samples=[FakeSample()],
        rag_service=rag_service,  # type: ignore[arg-type]
        top_k=4,
        retrieval_mode="hybrid",
        use_rerank=False,
        candidate_count=20,
        rerank_top_k=4,
        planner=FakePlanner(),  # type: ignore[arg-type]
    )

    assert rag_service.retrieve_calls == 0
    assert rows[0]["retrieved_count"] == 0
    assert rows[0]["plan"]["should_use_rag"] is False
    assert summary["planner_used_rate"] == 1.0


async def test_api_ragas_raises_on_row_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResult:
        def to_pandas(self) -> object:
            return []

    def fake_evaluate(**kwargs: object) -> FakeResult:
        return FakeResult()

    monkeypatch.setattr("evals.eval_api_answer._has_ragas", lambda: True)
    monkeypatch.setattr(
        "evals.eval_api_answer._create_eval_llm", lambda: ("llm", "model")
    )
    monkeypatch.setattr("ragas.evaluate", fake_evaluate)
    monkeypatch.setattr("ragas.metrics.collections.Faithfulness", lambda: object())
    monkeypatch.setattr("ragas.metrics.collections.AnswerRelevancy", lambda: object())
    monkeypatch.setattr("ragas.metrics.collections.AnswerCorrectness", lambda: object())

    with pytest.raises(RuntimeError, match="Ragas returned 0 rows"):
        await run_ragas(
            [
                {
                    "id": "case-1",
                    "query": "hello",
                    "answer": "answer",
                    "retrieved_contexts": ["ctx"],
                    "reference_answer": None,
                }
            ]
        )


async def test_api_401_refresh_updates_shared_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evals import eval_api_answer

    calls: list[str] = []

    async def fake_create_headers(client: object) -> dict[str, str]:
        return {"Authorization": f"Bearer token-{len(calls)}"}

    async def fake_query_api_answer(
        client: object,
        *,
        headers: dict[str, str],
        sample: object,
    ) -> tuple[str, dict, int]:
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            request = httpx.Request("POST", "http://test/api")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError(
                "unauthorized", request=request, response=response
            )
        return "answer", {"answer": {"search_context": {"chunks": []}}}, 1

    monkeypatch.setattr(eval_api_answer, "create_eval_headers", fake_create_headers)
    monkeypatch.setattr(eval_api_answer, "query_api_answer", fake_query_api_answer)

    headers_ref = {"headers": await eval_api_answer.create_eval_headers(object())}
    headers_lock = eval_api_answer.asyncio.Lock()

    await eval_api_answer.query_api_answer_with_refresh(
        object(),  # type: ignore[arg-type]
        headers_ref=headers_ref,
        headers_lock=headers_lock,
        sample=object(),
    )

    assert calls == ["Bearer token-0", "Bearer token-1"]
    assert headers_ref["headers"] == {"Authorization": "Bearer token-1"}
