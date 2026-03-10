import argparse
import asyncio
import json
import uuid
from pathlib import Path

from backend.ai.core import PromptManager
from backend.ai.core.prompt_templates import RAG_SYSTEM_TEMPLATE
from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.ai.providers.llm.llm_service import LLMService
from backend.ai.providers.llm.mock_provider import MockLLMService
from backend.core.config import settings
from backend.core.database import create_db_assets
from backend.models.schemas.chat_schema import LLMQueryDTO
from backend.services.rag_service import RAGService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from evals.common import ensure_parent_dir, load_samples


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
        "--output",
        type=Path,
        default=Path("evals/reports/answer_report.json"),
        help="Output report path",
    )
    return parser.parse_args()


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def _char_f1(pred: str, ref: str) -> float:
    pred_chars = [c for c in pred if not c.isspace()]
    ref_chars = [c for c in ref if not c.isspace()]
    if not pred_chars or not ref_chars:
        return 0.0
    pred_set = set(pred_chars)
    ref_set = set(ref_chars)
    overlap = len(pred_set & ref_set)
    precision = _safe_div(overlap, len(pred_set))
    recall = _safe_div(overlap, len(ref_set))
    return _safe_div(2 * precision * recall, precision + recall)


async def run(dataset: Path, top_k: int, llm_mode: str, output: Path) -> None:
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
        llm = MockLLMService() if llm_mode == "mock" else LLMService()
        prompt_manager = PromptManager(system_template=RAG_SYSTEM_TEMPLATE)

        rows = []
        keyword_recall_total = 0.0
        reference_f1_total = 0.0
        retrieval_hit_total = 0.0

        for sample in samples:
            chunks = await rag_service.retrieve(
                query_text=sample.query,
                kb_id=sample.kb_id,
                top_k=top_k,
            )
            context_chunks = [chunk["content"] for chunk in chunks]
            assembled = prompt_manager.assemble(
                history=[],
                current_query=sample.query,
                extra_vars={"context_chunks": context_chunks},
            )

            llm_query = LLMQueryDTO(
                session_id=uuid.uuid4(),
                query_text=sample.query,
                conversation_history=assembled.messages,
            )
            result = await llm.generate_response(llm_query)
            answer = result.content if result.success else ""

            keyword_recall = 0.0
            if sample.expected_keywords:
                hit_count = sum(
                    1 for kw in sample.expected_keywords if kw.lower() in answer.lower()
                )
                keyword_recall = _safe_div(hit_count, len(sample.expected_keywords))

            reference_f1 = 0.0
            if sample.reference_answer:
                reference_f1 = _char_f1(answer, sample.reference_answer)

            retrieval_hit = 0.0
            if sample.expected_chunk_ids:
                retrieved_ids = {chunk["id"] for chunk in chunks}
                retrieval_hit = (
                    1.0 if retrieved_ids.intersection(sample.expected_chunk_ids) else 0.0
                )

            keyword_recall_total += keyword_recall
            reference_f1_total += reference_f1
            retrieval_hit_total += retrieval_hit

            rows.append(
                {
                    "id": sample.id,
                    "query": sample.query,
                    "kb_id": str(sample.kb_id) if sample.kb_id else None,
                    "answer": answer,
                    "retrieved_count": len(chunks),
                    "keyword_recall": keyword_recall,
                    "reference_char_f1": reference_f1,
                    "retrieval_hit": retrieval_hit,
                }
            )

        summary = {
            "samples": len(samples),
            "top_k": top_k,
            "llm_mode": llm_mode,
            "avg_keyword_recall": _safe_div(keyword_recall_total, len(samples)),
            "avg_reference_char_f1": _safe_div(reference_f1_total, len(samples)),
            "retrieval_hit_rate": _safe_div(retrieval_hit_total, len(samples)),
        }
        report = {"summary": summary, "details": rows}

        ensure_parent_dir(output)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        print("Answer Eval Done")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"Report saved to: {output}")
    finally:
        await engine.dispose()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.dataset, args.top_k, args.llm, args.output))


if __name__ == "__main__":
    main()
