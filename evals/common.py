"""RAG eval shared utilities.

职责：数据集加载、检索分发、结果序列化、分类汇总等评测通用逻辑。
边界：不依赖 ragas / LLM 指标，只做工程侧的数据搬运与聚合。
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

VALID_RETRIEVAL_MODES = frozenset({"vector", "fulltext", "hybrid"})
PLAN_BOOL_KEYS = frozenset({"should_use_rag", "use_rerank"})

logger = logging.getLogger(__name__)

RetrievalMode = Literal["vector", "fulltext", "hybrid"]


@dataclass(slots=True)
class EvalSample:
    id: str
    query: str
    kb_id: uuid.UUID | None
    expected_chunk_ids: list[str] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    reference_answer: str | None = None
    category: str = "general"
    retrieval_mode: RetrievalMode | None = None
    expected_plan: dict[str, Any] | None = None
    must_refuse: bool = False
    notes: str | None = None


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
            expected_plan = payload.get("expected_plan")
            if expected_plan is not None and not isinstance(expected_plan, dict):
                raise ValueError(f"Line {line_no}: expected_plan 必须是 object 或 null")
            _validate_expected_plan(expected_plan, line_no=line_no)

            sample = EvalSample(
                id=str(payload.get("id") or f"line-{line_no}"),
                query=query,
                kb_id=kb_id,
                expected_chunk_ids=[
                    str(x) for x in payload.get("expected_chunk_ids", [])
                ],
                expected_keywords=[
                    str(x) for x in payload.get("expected_keywords", [])
                ],
                reference_answer=reference_answer,
                category=category,
                retrieval_mode=retrieval_mode,  # type: ignore[arg-type]
                expected_plan=expected_plan,
                must_refuse=bool(payload.get("must_refuse", False)),
                notes=notes,
            )
            samples.append(sample)
    if not samples:
        raise ValueError(f"数据集为空: {dataset_path}")
    return samples


def _validate_expected_plan(
    expected_plan: dict[str, Any] | None,
    *,
    line_no: int,
) -> None:
    if expected_plan is None:
        return
    for key in PLAN_BOOL_KEYS:
        if key in expected_plan and not isinstance(expected_plan[key], bool):
            raise ValueError(f"Line {line_no}: expected_plan.{key} 必须是 bool")
    retrieval_mode = expected_plan.get("retrieval_mode")
    if retrieval_mode is not None and retrieval_mode not in VALID_RETRIEVAL_MODES:
        raise ValueError(
            f"Line {line_no}: expected_plan.retrieval_mode 必须是 "
            f"{sorted(VALID_RETRIEVAL_MODES)} 之一"
        )


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def dataset_hash(dataset_path: Path) -> str:
    digest = hashlib.sha256()
    with dataset_path.open("rb") as dataset_file:
        for chunk in iter(lambda: dataset_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Unable to resolve git commit for eval snapshot: %s", exc)
        return None
    commit = result.stdout.strip()
    return commit or None


def build_run_metadata(
    *,
    kind: str,
    dataset_path: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    created_at = datetime.now(UTC).replace(microsecond=0)
    suffix = uuid.uuid4().hex[:8]
    return {
        "id": f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-{kind}-{suffix}",
        "kind": kind,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "dataset_path": str(dataset_path),
        "dataset_hash": dataset_hash(dataset_path),
        "git_commit": git_commit(),
        "config": config,
    }


def write_eval_report(output: Path, report: dict[str, Any]) -> None:
    ensure_parent_dir(output)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_rag_planner(provider: str | None = None) -> Any:
    from backend.services.rag_planning_service import RAGPlanningService

    return RAGPlanningService(provider=provider)


def build_rag_service(
    *,
    embedder: Any,
    vector_index_service: Any,
    top_k: int,
    reranker: Any | None = None,
    rerank_candidate_count: int,
    rerank_top_k: int,
) -> Any:
    from backend.services.rag_service import RAGService

    return RAGService(
        embedder=embedder,
        vector_index_service=vector_index_service,
        top_k=top_k,
        reranker=reranker,
        rerank_candidate_count=rerank_candidate_count,
        rerank_top_k=rerank_top_k,
    )


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


async def retrieve_chunks(
    *,
    rag_service: Any,
    query_text: str,
    kb_id: uuid.UUID | None,
    top_k: int,
    retrieval_mode: str,
    use_rerank: bool = False,
    candidate_count: int = 20,
    rerank_top_k: int = 4,
) -> list[dict]:
    """对单个 query 执行检索，支持 vector / fulltext / hybrid / rerank 四种路径。"""
    if use_rerank:
        return await rag_service.retrieve_with_rerank(
            query_text=query_text,
            kb_id=kb_id,
            top_k=rerank_top_k or top_k,
            candidate_count=candidate_count,
        )
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


def build_ragas_samples(
    rows: list[dict[str, Any]],
) -> list[Any]:
    """将内部 row 转换为 Ragas SingleTurnSample 列表。

    每个 row 需包含: query, retrieved_contexts(list[str]), answer, reference(str|None)
    """
    from ragas import SingleTurnSample

    samples: list[Any] = []
    for row in rows:
        samples.append(
            SingleTurnSample(
                user_input=row.get("query", ""),
                retrieved_contexts=row.get("retrieved_contexts", []),
                response=row.get("answer", ""),
                reference=row.get("reference_answer"),
            )
        )
    return samples
