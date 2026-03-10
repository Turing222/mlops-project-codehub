import argparse
import asyncio
import json
from pathlib import Path

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.core.config import settings
from backend.core.database import create_db_assets
from backend.services.rag_service import RAGService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from evals.common import ensure_parent_dir, load_samples


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
        "--output",
        type=Path,
        default=Path("evals/reports/retrieval_report.json"),
        help="Output report path",
    )
    return parser.parse_args()


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


async def run(dataset: Path, top_k: int, output: Path) -> None:
    samples = load_samples(dataset)
    engine, session_factory = create_db_assets()
    try:
        uow = SQLAlchemyUnitOfWork(session_factory)
        embedder = RAGEmbedderFactory.create(
            provider=settings.RAG_EMBED_PROVIDER,
            model_name=settings.RAG_EMBED_MODEL_NAME,
            device=settings.RAG_EMBED_DEVICE,
        )
        rag_service = RAGService(uow=uow, embedder=embedder, top_k=top_k)

        rows = []
        hit_total = 0.0
        recall_total = 0.0
        mrr_total = 0.0

        for sample in samples:
            chunks = await rag_service.retrieve(
                query_text=sample.query,
                kb_id=sample.kb_id,
                top_k=top_k,
            )
            retrieved_ids = [chunk["id"] for chunk in chunks]

            hit_at_k = 0.0
            recall_at_k = 0.0
            mrr = 0.0

            if sample.expected_chunk_ids:
                expected = set(sample.expected_chunk_ids)
                found = [cid for cid in retrieved_ids if cid in expected]
                hit_at_k = 1.0 if found else 0.0
                recall_at_k = _safe_div(len(set(found)), len(expected))
                first_rank = next(
                    (idx + 1 for idx, cid in enumerate(retrieved_ids) if cid in expected),
                    None,
                )
                mrr = _safe_div(1.0, first_rank) if first_rank else 0.0
            elif sample.expected_keywords:
                context_text = "\n".join(chunk["content"] for chunk in chunks).lower()
                keyword_hits = sum(
                    1 for kw in sample.expected_keywords if kw.lower() in context_text
                )
                hit_at_k = 1.0 if keyword_hits > 0 else 0.0
                recall_at_k = _safe_div(keyword_hits, len(sample.expected_keywords))
                mrr = hit_at_k

            hit_total += hit_at_k
            recall_total += recall_at_k
            mrr_total += mrr

            rows.append(
                {
                    "id": sample.id,
                    "query": sample.query,
                    "kb_id": str(sample.kb_id) if sample.kb_id else None,
                    "retrieved_count": len(chunks),
                    "hit_at_k": hit_at_k,
                    "recall_at_k": recall_at_k,
                    "mrr": mrr,
                    "retrieved_chunk_ids": retrieved_ids,
                }
            )

        summary = {
            "samples": len(samples),
            "top_k": top_k,
            "hit_at_k": _safe_div(hit_total, len(samples)),
            "recall_at_k": _safe_div(recall_total, len(samples)),
            "mrr": _safe_div(mrr_total, len(samples)),
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
    asyncio.run(run(args.dataset, args.top_k, args.output))


if __name__ == "__main__":
    main()
