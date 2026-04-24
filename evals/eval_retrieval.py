import argparse
import asyncio
import json
import time
from pathlib import Path

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.core.config import settings
from backend.core.database import create_db_assets
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval quality")
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
        "--retrieval-mode",
        choices=sorted(VALID_RETRIEVAL_MODES),
        default="vector",
        help="Default retrieval mode when sample does not specify one",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/reports/retrieval_report.json"),
        help="Output report path",
    )
    return parser.parse_args()
async def run(
    dataset: Path,
    top_k: int,
    retrieval_mode: str,
    output: Path,
) -> None:
    samples = load_samples(dataset)
    run_started_at = time.perf_counter()
    engine, session_factory = create_db_assets()
    try:
        uow = SQLAlchemyUnitOfWork(session_factory)
        embedder = RAGEmbedderFactory.create(
            provider=settings.RAG_EMBED_PROVIDER,
            model_name=settings.RAG_EMBED_MODEL_NAME,
        )
        rag_service = RAGService(uow=uow, embedder=embedder, top_k=top_k)

        rows = []
        hit_total = 0.0
        recall_total = 0.0
        mrr_total = 0.0
        retrieved_count_total = 0.0
        top_score_total = 0.0
        error_count = 0

        for sample in samples:
            sample_mode = sample.retrieval_mode or retrieval_mode
            sample_started_at = time.perf_counter()
            error_message: str | None = None

            try:
                chunks = await retrieve_chunks(
                    rag_service=rag_service,
                    query_text=sample.query,
                    kb_id=sample.kb_id,
                    top_k=top_k,
                    retrieval_mode=sample_mode,
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

            top_score = max((float(chunk.get("score") or 0.0) for chunk in chunks), default=0.0)
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
                    "must_refuse": sample.must_refuse,
                    "notes": sample.notes,
                    "retrieved_count": len(chunks),
                    "sample_latency_ms": int(
                        (time.perf_counter() - sample_started_at) * 1000
                    ),
                    "top_score": top_score,
                    "hit_at_k": hit_at_k,
                    "recall_at_k": recall_at_k,
                    "mrr": mrr,
                    "retrieved_chunk_ids": retrieved_ids,
                    "retrieved_chunks": serialize_retrieved_chunks(chunks),
                    "error_message": error_message,
                }
            )

        summary = {
            "samples": len(samples),
            "top_k": top_k,
            "default_retrieval_mode": retrieval_mode,
            "error_count": error_count,
            "hit_at_k": safe_div(hit_total, len(samples)),
            "recall_at_k": safe_div(recall_total, len(samples)),
            "mrr": safe_div(mrr_total, len(samples)),
            "avg_retrieved_count": safe_div(retrieved_count_total, len(samples)),
            "avg_top_score": safe_div(top_score_total, len(samples)),
            "runtime_sec": round(time.perf_counter() - run_started_at, 3),
            "per_category": summarize_by_category(
                rows,
                [
                    "hit_at_k",
                    "recall_at_k",
                    "mrr",
                    "retrieved_count",
                    "sample_latency_ms",
                    "top_score",
                ],
            ),
        }
        report = {"summary": summary, "details": rows}

        ensure_parent_dir(output)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        print("Retrieval Eval Done")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"Report saved to: {output}")
    finally:
        await engine.dispose()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.dataset, args.top_k, args.retrieval_mode, args.output))


if __name__ == "__main__":
    main()
