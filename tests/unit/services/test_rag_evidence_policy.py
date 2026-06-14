"""RAG evidence policy unit tests.

职责：验证 RAGEvidencePolicy 的相关性分数判断和拒绝/放行行为；边界：使用 monkeypatch 固定配置，不依赖真实 LLM；副作用：无。
"""

import pytest

from backend.services.rag_evidence_policy import RAGEvidencePolicy
from backend.services.rag_planning_service import RAGExecutionPlan


def test_hybrid_retrieval_raises_on_low_relevance_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.5,
    )
    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=False,
        candidate_count=20,
        rerank_top_k=4,
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=object(),
        rag_plan=plan,
        chunks=[
            {
                "retrieval_mode": "hybrid",
                "score": 1.0,
                "evidence_score": 0.2,
                "matched_by": ["vector"],
            }
        ],
        enable_rag_refusal=True,
    )

    assert decision.should_refuse is True
    assert decision.reason == "RAG hybrid 证据不足"


def test_hybrid_retrieval_passes_on_sufficient_relevance_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.5,
    )
    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=False,
        candidate_count=20,
        rerank_top_k=4,
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=object(),
        rag_plan=plan,
        chunks=[
            {
                "retrieval_mode": "hybrid",
                "score": 0.7,
                "evidence_score": 0.7,
                "matched_by": ["vector", "fulltext"],
            }
        ],
        enable_rag_refusal=True,
    )

    assert decision.should_refuse is False
    assert decision.reason == "RAG hybrid 双路命中证据充足"


def test_hybrid_dual_match_refuses_when_evidence_score_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.5,
    )
    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=False,
        candidate_count=20,
        rerank_top_k=4,
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=object(),
        rag_plan=plan,
        chunks=[
            {
                "retrieval_mode": "hybrid",
                "score": 1.0,
                "evidence_score": 0.2,
                "matched_by": ["vector", "fulltext"],
            }
        ],
        enable_rag_refusal=True,
    )

    assert decision.should_refuse is True
    assert decision.reason == "RAG hybrid 证据不足"


def test_hybrid_retrieval_passes_on_multiple_relevant_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.5,
    )
    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=False,
        candidate_count=20,
        rerank_top_k=4,
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=object(),
        rag_plan=plan,
        chunks=[
            {
                "retrieval_mode": "hybrid",
                "score": 1.0,
                "evidence_score": 0.7,
                "matched_by": ["vector"],
            },
            {
                "retrieval_mode": "hybrid",
                "score": 0.8,
                "evidence_score": 0.6,
                "matched_by": ["fulltext"],
            },
        ],
        enable_rag_refusal=True,
    )

    assert decision.should_refuse is False
    assert decision.reason == "RAG hybrid 多片段证据充足"


def test_rerank_score_below_threshold_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RERANK_SCORE",
        4.0,
    )
    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=True,
        candidate_count=20,
        rerank_top_k=4,
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=object(),
        rag_plan=plan,
        chunks=[
            {"retrieval_mode": "hybrid", "evidence_score": 0.9, "rerank_score": 2.0}
        ],
        enable_rag_refusal=True,
    )

    assert decision.should_refuse is True
    assert decision.reason == "RAG rerank 相关性不足"
    assert decision.best_rerank_score == 2.0


def test_rerank_score_at_threshold_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RERANK_SCORE",
        4.0,
    )
    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=True,
        candidate_count=20,
        rerank_top_k=4,
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=object(),
        rag_plan=plan,
        chunks=[
            {"retrieval_mode": "hybrid", "evidence_score": 0.1, "rerank_score": 4.0}
        ],
        enable_rag_refusal=True,
    )

    assert decision.should_refuse is False
    assert decision.reason == "RAG rerank 证据充足"


def test_refusal_disabled_allows_even_with_low_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=object(),
        rag_plan=plan,
        chunks=[{"retrieval_mode": "hybrid", "evidence_score": 0.0}],
        enable_rag_refusal=False,
    )

    assert decision.should_refuse is False
    assert decision.reason == "RAG 拒答策略未启用"


def test_external_context_evidence_allows_without_kb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.2,
    )
    plan = RAGExecutionPlan(
        should_use_rag=False,
        should_use_external_context=True,
        external_sources=["web"],
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=None,
        rag_plan=plan,
        chunks=[{"source_type": "web", "retrieval_mode": "external", "score": 0.7}],
        enable_rag_refusal=True,
    )

    assert decision.should_refuse is False
    assert decision.reason == "外部上下文证据充足"


def test_external_context_insufficient_without_kb_allows_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.9,
    )
    plan = RAGExecutionPlan(
        should_use_rag=False,
        should_use_external_context=True,
        external_sources=["web"],
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=None,
        rag_plan=plan,
        chunks=[{"source_type": "web", "retrieval_mode": "external", "score": 0.3}],
        enable_rag_refusal=True,
    )

    assert decision.should_refuse is False
    assert "外部上下文证据不充分" in decision.reason
