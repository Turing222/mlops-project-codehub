import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_RETRIEVAL_MODES = frozenset({"vector", "fulltext", "hybrid"})


@dataclass(slots=True)
class EvalSample:
    id: str
    query: str
    kb_id: uuid.UUID | None
    expected_chunk_ids: list[str]
    expected_keywords: list[str]
    reference_answer: str | None
    category: str
    retrieval_mode: str | None
    must_refuse: bool
    notes: str | None


def load_samples(dataset_path: Path) -> list[EvalSample]:
    samples: list[EvalSample] = []
    with dataset_path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            payload = json.loads(raw)
            query = str(payload.get("query", "")).strip()
            if not query:
                raise ValueError(f"Line {line_no}: query 不能为空")

            kb_value = payload.get("kb_id")
            kb_id = uuid.UUID(kb_value) if kb_value else None
            retrieval_mode = payload.get("retrieval_mode")
            if retrieval_mode is not None:
                retrieval_mode = str(retrieval_mode).strip().lower()
                if retrieval_mode not in VALID_RETRIEVAL_MODES:
                    raise ValueError(
                        f"Line {line_no}: retrieval_mode 必须是 "
                        f"{sorted(VALID_RETRIEVAL_MODES)} 之一"
                    )

            reference_answer = payload.get("reference_answer")
            if reference_answer is not None:
                reference_answer = str(reference_answer)

            category = str(payload.get("category") or "general").strip() or "general"
            notes = payload.get("notes")
            if notes is not None:
                notes = str(notes)

            sample = EvalSample(
                id=str(payload.get("id") or f"line-{line_no}"),
                query=query,
                kb_id=kb_id,
                expected_chunk_ids=[str(x) for x in payload.get("expected_chunk_ids", [])],
                expected_keywords=[str(x) for x in payload.get("expected_keywords", [])],
                reference_answer=reference_answer,
                category=category,
                retrieval_mode=retrieval_mode,
                must_refuse=bool(payload.get("must_refuse", False)),
                notes=notes,
            )
            samples.append(sample)
    if not samples:
        raise ValueError(f"数据集为空: {dataset_path}")
    return samples


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


async def retrieve_chunks(
    *,
    rag_service: Any,
    query_text: str,
    kb_id: uuid.UUID | None,
    top_k: int,
    retrieval_mode: str,
) -> list[dict]:
    if retrieval_mode == "fulltext":
        return await rag_service.retrieve_fulltext(
            query_text=query_text,
            kb_id=kb_id,
            top_k=top_k,
        )
    if retrieval_mode == "hybrid":
        return await rag_service.retrieve_hybrid(
            query_text=query_text,
            kb_id=kb_id,
            top_k=top_k,
        )
    return await rag_service.retrieve(
        query_text=query_text,
        kb_id=kb_id,
        top_k=top_k,
    )


def serialize_retrieved_chunks(
    chunks: list[dict],
    *,
    preview_chars: int = 160,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        content = str(chunk.get("content") or "")
        rows.append(
            {
                "id": chunk.get("id"),
                "score": chunk.get("score"),
                "distance": chunk.get("distance"),
                "source_type": chunk.get("source_type"),
                "file_id": chunk.get("file_id"),
                "message_id": chunk.get("message_id"),
                "content_preview": content[:preview_chars],
            }
        )
    return rows


def summarize_by_category(
    rows: list[dict[str, Any]],
    metric_names: list[str],
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        category = str(row.get("category") or "general")
        grouped[category].append(row)

    summary: dict[str, dict[str, float | int]] = {}
    for category, items in sorted(grouped.items()):
        category_summary: dict[str, float | int] = {"samples": len(items)}
        for metric_name in metric_names:
            values = [
                float(value)
                for item in items
                if (value := item.get(metric_name)) is not None
            ]
            category_summary[metric_name] = safe_div(sum(values), len(values))
        summary[category] = category_summary
    return summary
