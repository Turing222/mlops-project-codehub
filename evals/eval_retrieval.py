"""RAG 检索质量评测。

用法:
    # 普通 vector 检索
    python -m evals.eval_retrieval --dataset evals/dataset.sample.jsonl

    # hybrid 检索
    python -m evals.eval_retrieval --retrieval-mode hybrid

    # rerank 检索
    python -m evals.eval_retrieval --rerank --candidate-count 20 --rerank-top-k 4

    # 对比模式：同时跑 vector / hybrid / rerank 输出对比报告
    python -m evals.eval_retrieval --compare --output evals/reports/retrieval_compare.json

指标：
    hit_at_k, recall_at_k, mrr, avg_retrieved_count, avg_top_score, per_category
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.ai.providers.rerank.factory import RerankProviderFactory
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.infra.database import create_db_assets
from backend.models.schemas.chat.payloads import FeatureFlags
from backend.services.rag_planning_service import (
    RAG_PLANNER_FALLBACK_REASON,
    RAGPlanningService,
)
from backend.services.rag_service import RAGService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.services.vector_index_service import VectorIndexService
from evals.common import (
    VALID_RETRIEVAL_MODES,
    build_rag_service,
    build_run_metadata,
    create_rag_planner,
    load_samples,
    retrieve_chunks,
    safe_div,
    serialize_retrieved_chunks,
    summarize_by_category,
    write_eval_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval quality")
    parser.add_argument(
        "--dataset", type=Path, required=True, help="Path to JSONL dataset"
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=ai_settings.RAG_TOP_K,
        help="Top-K chunks to retrieve",
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=sorted(VALID_RETRIEVAL_MODES),
        default="hybrid",
        help="Default retrieval mode when sample does not specify one",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Enable rerank after candidate retrieval",
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        default=ai_settings.RAG_RERANK_CANDIDATE_COUNT,
        help="Candidate pool size for rerank",
    )
    parser.add_argument(
        "--rerank-top-k",
        type=int,
        default=ai_settings.RAG_RERANK_TOP_K,
        help="Top-K after rerank",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run all retrieval modes and compare side-by-side",
    )
    parser.add_argument(
        "--use-planner",
        action="store_true",
        help="Use RAG planner output instead of dataset/CLI retrieval mode",
    )
    parser.add_argument(
        "--planner-provider",
        default=None,
        help="Optional planner LLM provider override",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/reports/retrieval_report.json"),
        help="Output report path",
    )
    return parser.parse_args()


_RAW_METRIC_KEYS = (
    "hit_at_k",
    "recall_at_k",
    "mrr",
    "retrieved_count",
    "sample_latency_ms",
    "top_score",
)


async def _run_one_mode(
    *,
    samples: list,
    rag_service: RAGService,
    top_k: int,
    retrieval_mode: str,
    use_rerank: bool,
    candidate_count: int,
    rerank_top_k: int,
    planner: RAGPlanningService | None = None,
    infra_flags: FeatureFlags | None = None,
) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    hit_total = 0.0
    recall_total = 0.0
    mrr_total = 0.0
    retrieved_count_total = 0.0
    top_score_total = 0.0
    planner_latency_total = 0.0
    planner_used_total = 0
    planner_fallback_total = 0
    error_count = 0

    for sample in samples:
        sample_mode = sample.retrieval_mode or retrieval_mode
        sample_top_k = top_k
        sample_use_rerank = use_rerank
        sample_candidate_count = candidate_count
        sample_rerank_top_k = rerank_top_k
        planner_latency_ms: int | None = None
        planner_used = False
        planner_fallback = False
        plan_payload: dict[str, Any] | None = None
        skip_retrieval = False
        t0 = time.perf_counter()
        error_message: str | None = None

        if planner is not None:
            planner_started_at = time.perf_counter()
            try:
                plan = await planner.plan(
                    query_text=sample.query,
                    conversation_history=[],
                    kb_id=sample.kb_id,
                    infra_flags=infra_flags,
                )
                planner_latency_ms = int(
                    (time.perf_counter() - planner_started_at) * 1000
                )
                planner_latency_total += planner_latency_ms
                planner_used = True
                planner_used_total += 1
                planner_fallback = plan.reason == RAG_PLANNER_FALLBACK_REASON
                planner_fallback_total += int(planner_fallback)
                plan_payload = plan.model_dump()
                sample_mode = plan.retrieval_mode
                sample_top_k = plan.top_k
                sample_use_rerank = plan.use_rerank
                sample_candidate_count = plan.candidate_count
                sample_rerank_top_k = plan.rerank_top_k
                skip_retrieval = not plan.should_use_rag
            except Exception as exc:
                error_message = str(exc)
                error_count += 1

        chunks = []

        try:
            if not skip_retrieval and error_message is None:
                chunks = await retrieve_chunks(
                    rag_service=rag_service,
                    query_text=sample.query,
                    kb_id=sample.kb_id,
                    top_k=sample_top_k,
                    retrieval_mode=sample_mode,
                    use_rerank=sample_use_rerank,
                    candidate_count=sample_candidate_count,
                    rerank_top_k=sample_rerank_top_k,
                )
        except Exception as exc:
            chunks = []
            error_message = str(exc)
            error_count += 1

        retrieved_ids = [chunk["id"] for chunk in chunks]
        hit_at_k = 0.0
        recall_at_k = 0.0
        mrr = 0.0

        if sample.expected_chunk_ids:
            expected = set(sample.expected_chunk_ids)
            found = [cid for cid in retrieved_ids if cid in expected]
            hit_at_k = 1.0 if found else 0.0
            recall_at_k = safe_div(len(set(found)), len(expected))
            first_rank = next(
                (idx + 1 for idx, cid in enumerate(retrieved_ids) if cid in expected),
                None,
            )
            mrr = safe_div(1.0, first_rank) if first_rank else 0.0
        elif sample.expected_keywords:
            context_text = "\n".join(chunk["content"] for chunk in chunks).lower()
            keyword_hits = sum(
                1 for kw in sample.expected_keywords if kw.lower() in context_text
            )
            hit_at_k = 1.0 if keyword_hits > 0 else 0.0
            recall_at_k = safe_div(keyword_hits, len(sample.expected_keywords))
            mrr = hit_at_k

        top_score = max(
            (float(chunk.get("score") or 0.0) for chunk in chunks), default=0.0
        )
        retrieved_count_total += len(chunks)
        top_score_total += top_score
        hit_total += hit_at_k
        recall_total += recall_at_k
        mrr_total += mrr

        rows.append(
            {
                "id": sample.id,
                "category": sample.category,
                "query": sample.query,
                "kb_id": str(sample.kb_id) if sample.kb_id else None,
                "retrieval_mode": sample_mode,
                "has_rerank": sample_use_rerank,
                "planner_used": planner_used,
                "planner_fallback": planner_fallback,
                "planner_latency_ms": planner_latency_ms,
                "plan": plan_payload,
                "must_refuse": sample.must_refuse,
                "retrieved_count": len(chunks),
                "sample_latency_ms": int((time.perf_counter() - t0) * 1000),
                "top_score": top_score,
                "hit_at_k": hit_at_k,
                "recall_at_k": recall_at_k,
                "mrr": mrr,
                "retrieved_chunk_ids": retrieved_ids,
                "retrieved_chunks": serialize_retrieved_chunks(chunks),
                "error_message": error_message,
            }
        )

    total = len(samples)
    summary = {
        "samples": total,
        "top_k": top_k,
        "retrieval_mode": retrieval_mode,
        "rerank": use_rerank,
        "error_count": error_count,
        "hit_at_k": safe_div(hit_total, total),
        "recall_at_k": safe_div(recall_total, total),
        "mrr": safe_div(mrr_total, total),
        "avg_retrieved_count": safe_div(retrieved_count_total, total),
        "avg_top_score": safe_div(top_score_total, total),
        "planner_used_rate": safe_div(planner_used_total, total),
        "planner_fallback_rate": safe_div(planner_fallback_total, total),
        "avg_planner_latency_ms": safe_div(planner_latency_total, planner_used_total),
        "per_category": summarize_by_category(rows, list(_RAW_METRIC_KEYS)),
    }
    return rows, summary


async def run(args: argparse.Namespace) -> None:
    samples = load_samples(args.dataset)
    run_started_at = time.perf_counter()
    engine, session_factory = create_db_assets()
    try:
        uow = SQLAlchemyUnitOfWork(session_factory)
        embedding_profile = get_llm_model_config().resolve_embedding_profile(
            ai_settings.RAG_EMBED_PROVIDER
        )
        embedder = RAGEmbedderFactory.create(
            provider=embedding_profile.provider,
            model_name=embedding_profile.model,
            base_url=embedding_profile.resolve_base_url(),
            api_key=embedding_profile.resolve_api_key(),
            dimensions=embedding_profile.dimensions,
        )
        vector_index_service = VectorIndexService(uow=uow, embedder=embedder)
        planner = (
            create_rag_planner(args.planner_provider) if args.use_planner else None
        )

        if args.compare:
            compare_flags = FeatureFlags(enable_rag_rerank=True)
            reranker = (
                RerankProviderFactory.create()
                if compare_flags.enable_rag_rerank
                else None
            )

            modes = [
                ("vector", False),
                ("hybrid", False),
                ("hybrid", True),
            ]
            comparison: dict[str, dict] = {}
            for mode, rerank in modes:
                label = f"{mode}_rerank" if rerank else mode
                rag_service = build_rag_service(
                    embedder=embedder,
                    vector_index_service=vector_index_service,
                    top_k=args.top_k,
                    reranker=reranker,
                    rerank_candidate_count=args.candidate_count,
                    rerank_top_k=args.rerank_top_k,
                )
                _, summary = await _run_one_mode(
                    samples=samples,
                    rag_service=rag_service,
                    top_k=args.top_k,
                    retrieval_mode=mode,
                    use_rerank=rerank,
                    candidate_count=args.candidate_count,
                    rerank_top_k=args.rerank_top_k,
                    planner=planner,
                    infra_flags=compare_flags,
                )
                comparison[label] = summary
                print(f"\n--- {label} ---")
                print(json.dumps(summary, ensure_ascii=False, indent=2))

            report = {
                "run": build_run_metadata(
                    kind="retrieval",
                    dataset_path=args.dataset,
                    config=_run_config(args, embedding_profile, compare_flags),
                ),
                "runtime_sec": round(time.perf_counter() - run_started_at, 3),
                "comparison": comparison,
            }
        else:
            eval_flags = FeatureFlags(
                enable_rag_rerank=args.rerank,
                enable_rag_planner=args.use_planner,
            )
            reranker = (
                RerankProviderFactory.create()
                if (args.rerank or args.use_planner) and eval_flags.enable_rag_rerank
                else None
            )
            rag_service = build_rag_service(
                embedder=embedder,
                vector_index_service=vector_index_service,
                top_k=args.top_k,
                reranker=reranker,
                rerank_candidate_count=args.candidate_count,
                rerank_top_k=args.rerank_top_k,
            )

            details, summary = await _run_one_mode(
                samples=samples,
                rag_service=rag_service,
                top_k=args.top_k,
                retrieval_mode=args.retrieval_mode,
                use_rerank=args.rerank,
                candidate_count=args.candidate_count,
                rerank_top_k=args.rerank_top_k,
                planner=planner,
                infra_flags=eval_flags,
            )
            summary["runtime_sec"] = round(time.perf_counter() - run_started_at, 3)
            report = {
                "run": build_run_metadata(
                    kind="retrieval",
                    dataset_path=args.dataset,
                    config=_run_config(args, embedding_profile, eval_flags),
                ),
                "summary": summary,
                "details": details,
            }

        write_eval_report(args.output, report)

        print(f"\nReport saved to: {args.output}")
    finally:
        await engine.dispose()


def _run_config(
    args: argparse.Namespace,
    embedding_profile: Any,
    infra_flags: FeatureFlags,
) -> dict[str, Any]:
    return {
        "cli_args": {
            "top_k": args.top_k,
            "retrieval_mode": args.retrieval_mode,
            "rerank": args.rerank,
            "candidate_count": args.candidate_count,
            "rerank_top_k": args.rerank_top_k,
            "compare": args.compare,
            "use_planner": args.use_planner,
            "planner_provider": args.planner_provider,
            "output": str(args.output),
        },
        "models": {
            "embedding_provider": embedding_profile.provider,
            "embedding_model": embedding_profile.model,
            "embedding_base_url_configured": bool(embedding_profile.resolve_base_url()),
            "planner_provider": args.planner_provider,
        },
        "rag": {
            "planner_enabled": args.use_planner,
            "config_rerank_enabled": infra_flags.enable_rag_rerank,
        },
    }


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
