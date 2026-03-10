import json
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class EvalSample:
    id: str
    query: str
    kb_id: uuid.UUID | None
    expected_chunk_ids: list[str]
    expected_keywords: list[str]
    reference_answer: str | None


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
            sample = EvalSample(
                id=str(payload.get("id") or f"line-{line_no}"),
                query=query,
                kb_id=kb_id,
                expected_chunk_ids=[str(x) for x in payload.get("expected_chunk_ids", [])],
                expected_keywords=[str(x) for x in payload.get("expected_keywords", [])],
                reference_answer=payload.get("reference_answer"),
            )
            samples.append(sample)
    if not samples:
        raise ValueError(f"数据集为空: {dataset_path}")
    return samples


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
