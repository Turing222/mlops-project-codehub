"""RAG 端到端回答质量评测（Ragas LLM-as-Judge）。

用法:
    python -m evals.eval_answer \
      --dataset evals/dataset.sample.jsonl \
      --output evals/reports/answer_report.json

    # 启用 rerank
    python -m evals.eval_answer --rerank --output evals/reports/answer_report.json

需要配置环境变量（Ragas 评估 LLM）:
    OPENAI_API_KEY  或 EVAL_LLM_API_KEY
    EVAL_LLM_BASE_URL   (可选，默认 https://api.openai.com/v1)
    EVAL_LLM_MODEL       (可选，默认 gpt-4o)

指标：
    Ragas: faithfulness, answer_relevancy, answer_correctness
    工程: retrieval_hit_rate, avg_llm_latency_ms, avg_completion_tokens
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.ai.providers.rerank.factory import RerankProviderFactory
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.infra.database import create_db_assets
from backend.models.schemas.chat.dto import LLMQueryDTO
from backend.models.schemas.chat.payloads import FeatureFlags
from backend.services.rag_planning_service import (
    RAG_PLANNER_FALLBACK_REASON,
)
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
    parser = argparse.ArgumentParser(
        description="Evaluate RAG answer quality with Ragas"
    )
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
    )
    parser.add_argument(
        "--rerank-top-k",
        type=int,
        default=ai_settings.RAG_RERANK_TOP_K,
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
        default=Path("evals/reports/answer_report.json"),
        help="Output report path",
    )
    return parser.parse_args()


def _create_eval_llm():
    """创建 Ragas 评估用的 LLM 实例。

    优先使用 OPENAI_API_KEY / EVAL_LLM_* 环境变量配置，
    否则回退到项目 LLM 配置。
    """
    from ragas.llms import llm_factory

    api_key = os.getenv("EVAL_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("EVAL_LLM_BASE_URL", "")
    model = os.getenv("EVAL_LLM_MODEL", "gpt-4o")

    if not api_key:
        profile = get_llm_model_config().resolve_profile()
        api_key = profile.resolve_api_key()
        base_url = profile.resolve_base_url() or base_url
        if not api_key:
            raise RuntimeError(
                "评测需要 LLM API Key。请设置 OPENAI_API_KEY 或 EVAL_LLM_API_KEY 或 LLM_API_KEY。"
            )

    kwargs: dict[str, str] = {"provider": "openai", "model": model, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return llm_factory(**kwargs), model  # type: ignore[call-arg]


async def run(args: argparse.Namespace) -> None:
    samples = load_samples(args.dataset)
    run_started_at = time.perf_counter()
    engine, session_factory = create_db_assets()

    try:
        # ── 服务初始化 ──────────────────────────────────────────────
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

        llm_service = LLMProviderFactory.create()
        reranker = (
            RerankProviderFactory.create() if args.rerank or args.use_planner else None
        )
        rag_service = build_rag_service(
            embedder=embedder,
            vector_index_service=vector_index_service,
            top_k=args.top_k,
            reranker=reranker,
            rerank_candidate_count=args.candidate_count,
            rerank_top_k=args.rerank_top_k,
        )
        planner = (
            create_rag_planner(args.planner_provider) if args.use_planner else None
        )
        infra_flags = FeatureFlags(
            enable_rag_rerank=args.rerank,
            enable_rag_planner=args.use_planner,
        )
        chat_context_builder = ChatContextBuilder()

        # ── 逐样本生成回答 ──────────────────────────────────────────
        rows: list[dict[str, Any]] = []
        retrieval_hit_total = 0.0
        llm_latency_total = 0.0
        total_latency_total = 0.0
        completion_tokens_total = 0.0
        error_count = 0
        ragas_samples: list[Any] = []
        eval_model: str | None = None

        for sample in samples:
            sample_mode = sample.retrieval_mode or args.retrieval_mode
            sample_top_k = args.top_k
            sample_use_rerank = args.rerank
            sample_candidate_count = args.candidate_count
            sample_rerank_top_k = args.rerank_top_k
            plan_payload: dict[str, Any] | None = None
            planner_used = False
            planner_fallback = False
            planner_latency_ms: int | None = None
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
                    planner_used = True
                    planner_fallback = plan.reason == RAG_PLANNER_FALLBACK_REASON
                    plan_payload = plan.model_dump()
                    sample_mode = plan.retrieval_mode
                    sample_top_k = plan.top_k
                    sample_use_rerank = plan.use_rerank
                    sample_candidate_count = plan.candidate_count
                    sample_rerank_top_k = plan.rerank_top_k
                except Exception as exc:
                    error_message = str(exc)
                    error_count += 1

            # 检索
            try:
                if plan_payload is not None and not plan_payload.get(
                    "should_use_rag", True
                ):
                    chunks = []
                else:
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

            # 组装 Prompt（与 Worker 路径一致）
            prepared = chat_context_builder.build_from_chunks(
                history_messages=[],
                current_query=sample.query,
                kb_id=sample.kb_id,
                rag_chunks=chunks,
            )

            # 生成
            llm_query = LLMQueryDTO(
                session_id=uuid.uuid4(),
                query_text=sample.query,
                conversation_history=prepared.assembled_prompt.messages,
            )
            llm_started_at = time.perf_counter()
            try:
                result = await llm_service.generate_response(llm_query)
                answer = result.content if result.success else ""
                if not result.success and result.error_message:
                    error_message = result.error_message
                    error_count += 1
            except Exception as exc:
                answer = ""
                error_message = str(exc)
                error_count += 1
                result = None

            llm_latency_ms = (
                result.latency_ms
                if result and result.latency_ms is not None
                else int((time.perf_counter() - llm_started_at) * 1000)
            )
            total_latency_ms = int((time.perf_counter() - t0) * 1000)

            # 检索命中率
            retrieval_hit = 0.0
            if sample.expected_chunk_ids:
                retrieved_ids = {chunk["id"] for chunk in chunks}
                retrieval_hit = (
                    1.0
                    if retrieved_ids.intersection(sample.expected_chunk_ids)
                    else 0.0
                )
            retrieval_hit_total += retrieval_hit

            # 记录 tokens
            if result and result.completion_tokens is not None:
                completion_tokens_total += result.completion_tokens

            llm_latency_total += llm_latency_ms
            total_latency_total += total_latency_ms

            # 提取 contexts 文本
            context_texts = [str(chunk.get("content") or "") for chunk in chunks]

            # 收集 Ragas 样本（仅有效回答）
            ragas_index: int | None = None
            if answer.strip() and context_texts:
                from ragas import SingleTurnSample

                ragas_index = len(ragas_samples)
                ragas_samples.append(
                    SingleTurnSample(
                        user_input=sample.query,
                        retrieved_contexts=context_texts,
                        response=answer,
                        reference=sample.reference_answer,
                    )
                )

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
                    "notes": sample.notes,
                    "answer": answer,
                    "reference_answer": sample.reference_answer,
                    "retrieved_count": len(chunks),
                    "retrieval_latency_ms": None,
                    "llm_latency_ms": llm_latency_ms,
                    "total_latency_ms": total_latency_ms,
                    "prompt_tokens": result.prompt_tokens if result else None,
                    "completion_tokens": result.completion_tokens if result else None,
                    "retrieval_hit": retrieval_hit,
                    "retrieved_chunk_ids": [chunk["id"] for chunk in chunks],
                    "retrieved_chunks": serialize_retrieved_chunks(chunks),
                    "retrieved_contexts": context_texts,
                    "ragas_index": ragas_index,
                    "error_message": error_message,
                }
            )

        # ── 运行 Ragas 指标 ─────────────────────────────────────────
        ragas_scores: dict[str, float | str] = {}
        ragas_details: list[dict] = []

        if ragas_samples and _has_ragas():
            from ragas import EvaluationDataset, evaluate
            from ragas.metrics.collections import (
                AnswerCorrectness,
                AnswerRelevancy,
                Faithfulness,
            )

            eval_llm, eval_model = _create_eval_llm()

            metrics = [
                Faithfulness(),  # type: ignore[call-arg]
                AnswerRelevancy(),  # type: ignore[call-arg]
            ]
            has_reference = any(
                s.reference_answer for s in samples if s.reference_answer
            )
            if has_reference:
                metrics.append(AnswerCorrectness())  # type: ignore[call-arg]

            try:
                dataset = EvaluationDataset(samples=ragas_samples)
                ragas_result = evaluate(
                    dataset=dataset,
                    metrics=metrics,  # type: ignore[arg-type]
                    llm=eval_llm,
                )
                ragas_df = ragas_result.to_pandas()  # type: ignore[union-attr]
                ragas_scores = {
                    col: float(ragas_df[col].mean())
                    for col in ragas_df.columns
                    if col
                    not in ("user_input", "retrieved_contexts", "response", "reference")
                }
                # 逐样本详情
                for _, srow in ragas_df.iterrows():
                    detail: dict[str, Any] = {}
                    for col in ragas_df.columns:
                        val = srow[col]
                        if isinstance(val, (int, float, str, bool)) or val is None:
                            detail[col] = val
                    ragas_details.append(detail)
            except Exception as exc:
                ragas_scores["ragas_error"] = str(exc)

        # ── 汇总报告 ────────────────────────────────────────────────
        total = len(samples)
        summary: dict[str, Any] = {
            "samples": total,
            "top_k": args.top_k,
            "default_retrieval_mode": args.retrieval_mode,
            "rerank": args.rerank,
            "error_count": error_count,
            "retrieval_hit_rate": safe_div(retrieval_hit_total, total),
            "avg_llm_latency_ms": safe_div(llm_latency_total, total),
            "avg_total_latency_ms": safe_div(total_latency_total, total),
            "avg_completion_tokens": safe_div(completion_tokens_total, total),
            "runtime_sec": round(time.perf_counter() - run_started_at, 3),
            "ragas_scores": ragas_scores,
            "per_category": summarize_by_category(
                rows,
                [
                    "retrieval_hit",
                    "llm_latency_ms",
                    "total_latency_ms",
                    "completion_tokens",
                    "retrieved_count",
                ],
            ),
        }

        # 合并 Ragas 逐样本分数到 details（通过 ragas_index 映射，避免空样本错位）
        if ragas_details:
            for row in rows:
                ri = row.get("ragas_index")
                if isinstance(ri, int) and 0 <= ri < len(ragas_details):
                    for key, val in ragas_details[ri].items():
                        row[f"ragas_{key}"] = val

        report = {
            "run": build_run_metadata(
                kind="answer",
                dataset_path=args.dataset,
                config=_run_config(args, embedding_profile, eval_model, infra_flags),
            ),
            "summary": summary,
            "details": rows,
        }

        write_eval_report(args.output, report)

        print("\nAnswer Eval Done")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"Report saved to: {args.output}")
    finally:
        await engine.dispose()


def _run_config(
    args: argparse.Namespace,
    embedding_profile: Any,
    eval_model: str | None,
    infra_flags: FeatureFlags,
) -> dict[str, Any]:
    generation_profile = get_llm_model_config().resolve_profile()
    return {
        "cli_args": {
            "top_k": args.top_k,
            "retrieval_mode": args.retrieval_mode,
            "rerank": args.rerank,
            "candidate_count": args.candidate_count,
            "rerank_top_k": args.rerank_top_k,
            "use_planner": args.use_planner,
            "planner_provider": args.planner_provider,
            "output": str(args.output),
        },
        "models": {
            "generation_provider": generation_profile.provider,
            "generation_model": generation_profile.model,
            "generation_base_url_configured": bool(
                generation_profile.resolve_base_url()
            ),
            "embedding_provider": embedding_profile.provider,
            "embedding_model": embedding_profile.model,
            "embedding_base_url_configured": bool(embedding_profile.resolve_base_url()),
            "eval_model": eval_model or os.getenv("EVAL_LLM_MODEL", "gpt-4o"),
            "planner_provider": args.planner_provider,
        },
        "rag": {
            "planner_enabled": args.use_planner,
            "config_rerank_enabled": infra_flags.enable_rag_rerank,
        },
    }


def _has_ragas() -> bool:
    try:
        import ragas  # noqa: F401

        return True
    except ImportError:
        return False


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
