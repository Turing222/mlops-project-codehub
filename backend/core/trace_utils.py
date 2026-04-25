from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import context, propagate, trace
from opentelemetry.trace import Span, Status, StatusCode

_TRACER = trace.get_tracer("backend.business")


def _coerce_attribute(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple):
        items = [_coerce_attribute(item) for item in value]
        return [item for item in items if item is not None]
    return str(value)


def set_span_attributes(span: Span, attributes: Mapping[str, Any]) -> None:
    for key, value in attributes.items():
        coerced = _coerce_attribute(value)
        if coerced is not None:
            span.set_attribute(key, coerced)


def inject_trace_context() -> dict[str, str]:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


@contextmanager
def use_trace_context(carrier: Mapping[str, str] | None) -> Iterator[None]:
    if not carrier:
        yield
        return

    token = context.attach(propagate.extract(dict(carrier)))
    try:
        yield
    finally:
        context.detach(token)


@contextmanager
def trace_span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[Span]:
    with _TRACER.start_as_current_span(name) as span:
        if attributes:
            set_span_attributes(span, attributes)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
