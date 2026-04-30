import argparse
import asyncio
import json
import time
import uuid
from collections import Counter
from pathlib import Path

from backend.ai.core import PromptManager
from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.ai.core.prompt_templates import RAG_SYSTEM_TEMPLATE
from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.ai.providers.llm.llm_service import LLMService
from backend.ai.providers.llm.mock_provider import MockLLMService
from backend.config.llm import get_llm_model_config
from backend.core.config import settings
from backend.core.database import create_db_assets
from backend.models.schemas.chat_schema import LLMQueryDTO
from backend.services.rag_service import RAGService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from evals.common import (
    VALID_RETRIEVAL_MODES,
    ensure_parent_dir,
    load_samples,
    retrieve_chunks,
    safe_div,
    serialize_retrieved_chunks,
    summarize_by_category,
)

REFUSAL_HINTS = (
    "不知道",
    "无法回答",
    "无法确认",
    "未提及",
    "未找到",
    "没有提供",
    "没有足够信息",
    "无法根据提供的内容",
    "无法从给定内容中",
    "insufficient information",
    "not enough information",
    "not provided",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG answer quality")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/dataset.sample.jsonl"),
        help="Path to JSONL dataset",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=settings.RAG_TOP_K,
        help="Top-K chunks to retrieve",
    )
    parser.add_argument(
        "--llm",
        choices=("mock", "real"),
        default="mock",
        help="Use mock or real llm backend",
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=sorted(VALID_RETRIEVAL_MODES),
        default="vector",
        help="Default retrieval mode when sample does not specify one",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/reports/answer_report.json"),
        help="Output report path",
    )
    return parser.parse_args()


def _char_f1(pred: str, ref: str) -> float:
    pred_chars = [c for c in pred if not c.isspace()]
    ref_chars = [c for c in ref if not c.isspace()]
    if not pred_chars or not ref_chars:
        return 0.0
    pred_counter = Counter(pred_chars)
    ref_counter = Counter(ref_chars)
    overlap = sum((pred_counter & ref_counter).values())
    precision = safe_div(overlap, len(pred_chars))
    recall = safe_div(overlap, len(ref_chars))
    return safe_div(2 * precision * recall, precision + recall)


def _score_refusal(answer: str) -> float:
    normalized = answer.strip().lower()
    if not normalized:
        return 0.0
    if any(hint in normalized for hint in REFUSAL_HINTS):
        return 1.0
    return 0.0


def _compute_answer_score(
    *,
    must_refuse: bool,
    keyword_recall: float,
    reference_f1: float,
    refusal_score: float | None,
) -> float:
    if must_refuse:
        return refusal_score or 0.0
    components = [value for value in (keyword_recall, reference_f1) if value > 0]
    if not components:
        return 0.0
    return safe_div(sum(components), len(components))


async def run(
    dataset: Path,
    top_k: int,
    llm_mode: str,
    retrieval_mode: str,
    output: Path,
) -> None:
    samples = load_samples(dataset)
    run_started_at = time.perf_counter()
    engine, session_factory = create_db_assets()
    try:
        uow = SQLAlchemyUnitOfWork(session_factory)
        embedding_profile = get_llm_model_config().resolve_embedding_profile(
            settings.RAG_EMBED_PROVIDER
        )
        embedder = RAGEmbedderFactory.create(
            provider=embedding_profile.provider,
            model_name=embedding_profile.model,
            base_url=embedding_profile.resolve_base_url(),
            api_key=embedding_profile.resolve_api_key(),
            dimensions=embedding_profile.dimensions,
        )
        rag_service = RAGService(uow=uow, embedder=embedder, top_k=top_k)
        llm = MockLLMService() if llm_mode == "mock" else LLMService()
        prompt_manager = PromptManager(system_template=RAG_SYSTEM_TEMPLATE)

        rows = []
        keyword_recall_total = 0.0
        reference_f1_total = 0.0
        retrieval_hit_total = 0.0
        answer_score_total = 0.0
        llm_latency_total = 0.0
        total_latency_total = 0.0
        completion_tokens_total = 0.0
        prompt_tokens_total = 0.0
        prompt_token_samples = 0
        refusal_score_total = 0.0
        refusal_samples = 0
        error_count = 0

        for sample in samples:
            sample_mode = sample.retrieval_mode or retrieval_mode
            sample_started_at = time.perf_counter()
            error_message: str | None = None

            try:
                retrieval_started_at = time.perf_counter()
                chunks = await retrieve_chunks(
                    rag_service=rag_service,
                    query_text=sample.query,
                    kb_id=sample.kb_id,
                    top_k=top_k,
                    retrieval_mode=sample_mode,
                )
                retrieval_latency_ms = int(
                    (time.perf_counter() - retrieval_started_at) * 1000
                )
            except Exception as exc:
                chunks = []
                retrieval_latency_ms = None
                error_message = str(exc)
                error_count += 1

            rag_references = ChatContextBuilder._build_rag_references(
                kb_id=sample.kb_id,
                query_text=sample.query,
                rag_chunks=chunks,
            )
            assembled = prompt_manager.assemble(
                history=[],
                current_query=sample.query,
                extra_vars={"context_chunks": rag_references.context_chunks},
            )

            llm_query = LLMQueryDTO(
                session_id=uuid.uuid4(),
                query_text=sample.query,
                conversation_history=assembled.messages,
            )
            llm_started_at = time.perf_counter()
            try:
                result = await llm.generate_response(llm_query)
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
            total_latency_ms = int((time.perf_counter() - sample_started_at) * 1000)

            keyword_recall = 0.0
            if sample.expected_keywords:
                hit_count = sum(
                    1 for kw in sample.expected_keywords if kw.lower() in answer.lower()
                )
                keyword_recall = safe_div(hit_count, len(sample.expected_keywords))

            reference_f1 = 0.0
            if sample.reference_answer:
                reference_f1 = _char_f1(answer, sample.reference_answer)

            retrieval_hit = 0.0
            if sample.expected_chunk_ids:
                retrieved_ids = {chunk["id"] for chunk in chunks}
                retrieval_hit = (
                    1.0
                    if retrieved_ids.intersection(sample.expected_chunk_ids)
                    else 0.0
                )

            refusal_score: float | None = None
            if sample.must_refuse:
                refusal_samples += 1
                refusal_score = _score_refusal(answer)
                refusal_score_total += refusal_score

            answer_score = _compute_answer_score(
                must_refuse=sample.must_refuse,
                keyword_recall=keyword_recall,
                reference_f1=reference_f1,
                refusal_score=refusal_score,
            )

            keyword_recall_total += keyword_recall
            reference_f1_total += reference_f1
            retrieval_hit_total += retrieval_hit
            answer_score_total += answer_score
            llm_latency_total += llm_latency_ms
            total_latency_total += total_latency_ms

            if result and result.completion_tokens is not None:
                completion_tokens_total += result.completion_tokens
            if result and result.prompt_tokens is not None:
                prompt_tokens_total += result.prompt_tokens
                prompt_token_samples += 1

            rows.append(
                {
                    "id": sample.id,
                    "category": sample.category,
                    "query": sample.query,
                    "kb_id": str(sample.kb_id) if sample.kb_id else None,
                    "retrieval_mode": sample_mode,
                    "must_refuse": sample.must_refuse,
                    "notes": sample.notes,
                    "answer": answer,
                    "llm_mode": llm_mode,
                    "retrieved_count": len(chunks),
                    "retrieval_latency_ms": retrieval_latency_ms,
                    "llm_latency_ms": llm_latency_ms,
                    "total_latency_ms": total_latency_ms,
                    "prompt_tokens": result.prompt_tokens if result else None,
                    "completion_tokens": result.completion_tokens if result else None,
                    "keyword_recall": keyword_recall,
                    "reference_char_f1": reference_f1,
                    "retrieval_hit": retrieval_hit,
                    "refusal_score": refusal_score,
                    "answer_score": answer_score,
                    "retrieved_chunk_ids": [chunk["id"] for chunk in chunks],
                    "retrieved_chunks": serialize_retrieved_chunks(chunks),
                    "error_message": error_message,
                }
            )

        summary = {
            "samples": len(samples),
            "top_k": top_k,
            "llm_mode": llm_mode,
            "default_retrieval_mode": retrieval_mode,
            "error_count": error_count,
            "avg_keyword_recall": safe_div(keyword_recall_total, len(samples)),
            "avg_reference_char_f1": safe_div(reference_f1_total, len(samples)),
            "retrieval_hit_rate": safe_div(retrieval_hit_total, len(samples)),
            "avg_answer_score": safe_div(answer_score_total, len(samples)),
            "avg_llm_latency_ms": safe_div(llm_latency_total, len(samples)),
            "avg_total_latency_ms": safe_div(total_latency_total, len(samples)),
            "avg_completion_tokens": safe_div(completion_tokens_total, len(samples)),
            "avg_prompt_tokens": safe_div(prompt_tokens_total, prompt_token_samples),
            "refusal_samples": refusal_samples,
            "refusal_success_rate": safe_div(refusal_score_total, refusal_samples),
            "runtime_sec": round(time.perf_counter() - run_started_at, 3),
            "per_category": summarize_by_category(
                rows,
                [
                    "keyword_recall",
                    "reference_char_f1",
                    "retrieval_hit",
                    "refusal_score",
                    "answer_score",
                    "retrieval_latency_ms",
                    "llm_latency_ms",
                    "total_latency_ms",
                    "completion_tokens",
                ],
            ),
        }
        report = {"summary": summary, "details": rows}

        ensure_parent_dir(output)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print("Answer Eval Done")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"Report saved to: {output}")
    finally:
        await engine.dispose()


def main() -> None:
    args = parse_args()
    asyncio.run(
        run(
            args.dataset,
            args.top_k,
            args.llm,
            args.retrieval_mode,
            args.output,
        )
    )


if __name__ == "__main__":
    main()
