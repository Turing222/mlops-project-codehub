"""Business tracing helpers.

职责：封装业务 span、trace context 注入/恢复和 span attribute 类型转换。
边界：本模块不初始化 OTel provider；provider 生命周期由 telemetry 负责。
失败处理：trace_span 会记录异常并把 span 标记为 error 后继续抛出。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from opentelemetry import context, propagate, trace
from opentelemetry.trace import Span, Status, StatusCode

_TRACER = trace.get_tracer("backend.business")
REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="")


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
    """设置 span 属性，并把 UUID 等对象转换为 OTel 支持的类型。"""
    for key, value in attributes.items():
        coerced = _coerce_attribute(value)
        if coerced is not None:
            span.set_attribute(key, coerced)


def set_current_span_attributes(attributes: Mapping[str, Any]) -> None:
    """为当前 span 设置属性。"""
    set_span_attributes(trace.get_current_span(), attributes)


def current_trace_id(fallback: str | None = None) -> str:
    """返回当前 trace_id；缺失时使用 fallback 或生成随机 id。"""
    span_ctx = trace.get_current_span().get_span_context()
    if span_ctx and span_ctx.trace_id:
        return f"{span_ctx.trace_id:032x}"
    return fallback if fallback is not None else uuid.uuid4().hex


def inject_trace_context() -> dict[str, str]:
    """把当前 OTel context 注入可序列化 carrier。"""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


@contextmanager
def use_trace_context(carrier: Mapping[str, str] | None) -> Iterator[None]:
    """在同步上下文中恢复传入的 OTel trace context。"""
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
    """创建业务 span，并在异常时记录错误状态。"""
    with _TRACER.start_as_current_span(name) as span:
        if attributes:
            set_span_attributes(span, attributes)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
