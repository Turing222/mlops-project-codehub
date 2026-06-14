"""Small timing helpers for chat workflow metrics."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any


def perf_start() -> float:
    return time.perf_counter()


def elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def merge_metrics(
    payload: dict[str, Any] | None,
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(payload or {})
    existing_metrics = merged.get("metrics")
    metric_payload = (
        dict(existing_metrics) if isinstance(existing_metrics, dict) else {}
    )
    metric_payload.update(
        {key: value for key, value in metrics.items() if value is not None}
    )
    if metric_payload:
        merged["metrics"] = metric_payload
    return merged


def tokens_per_second(tokens_output: int, elapsed: int | None) -> float | None:
    if elapsed is None or elapsed <= 0:
        return None
    return round(tokens_output / (elapsed / 1000), 2)
