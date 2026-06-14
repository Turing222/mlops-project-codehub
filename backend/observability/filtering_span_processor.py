"""Filtering SpanProcessor for Langfuse export.

职责：包裹 Langfuse SDK 的 SpanProcessor，按 span name/instrumentation scope 过滤，
     只让 LLM 相关的 span 导出到 Langfuse，阻挡普通 HTTP / rate_limit 等噪声 span。
边界：本模块只影响 Langfuse 导出，不影响 OTLP (Jaeger) 的完整 trace。
设计：过滤在 on_end 执行（span name 和 attributes 已完整）；on_start 始终委托，
     确保 Langfuse propagate_attributes 仍然生效。
"""

from __future__ import annotations

from collections.abc import Callable

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor


class FilteringSpanProcessor(SpanProcessor):
    """Wraps a delegate SpanProcessor, only forwarding spans that pass the filter.

    ``on_start`` is always delegated so that Langfuse SDK's ``propagate_attributes``
    still binds user_id / session_id / tags to the span — the actual export decision
    is deferred to ``on_end`` where the span name and attributes are finalized.
    """

    def __init__(
        self,
        delegate: SpanProcessor,
        *,
        allow_fn: Callable[[ReadableSpan], bool],
    ) -> None:
        self._delegate = delegate
        self._allow_fn = allow_fn

    # ------------------------------------------------------------------
    # SpanProcessor interface
    # ------------------------------------------------------------------

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self._delegate.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        if self._allow_fn(span):
            self._delegate.on_end(span)

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


# ---------------------------------------------------------------------------
# Filter predicate
# ---------------------------------------------------------------------------

# instrumentation scope names that should always be blocked from Langfuse.
# (Defense-in-depth: these are also handled by Langfuse SDK's
#  ``blocked_instrumentation_scopes``, but the predicate provides a second layer.)
_BLOCKED_INSTRUMENTATION_SCOPES = frozenset(
    {
        "opentelemetry.instrumentation.fastapi",
        "opentelemetry.instrumentation.sqlalchemy",
    },
)

# Span name prefixes from the ``backend.business`` tracer that are LLM-relevant
# and should be exported to Langfuse.  Anything *not* matching is treated as noise
# (e.g. ``http.rate_limit``, ``concurrency.llm``) and dropped.
_ALLOWED_SPAN_PREFIXES = (
    "llm.",
    "chat.",
    "rag.",
    "embedding.",
    "rerank.",
    "vector_index.",
    "knowledge.",
    "external_context.",
    "repo_analysis.",
    "taskiq.",
)


def should_export_to_langfuse(span: ReadableSpan) -> bool:
    """Return True if *span* should be exported to Langfuse."""
    scope = span.instrumentation_scope

    # 1. Langfuse SDK's own spans — always allow (internal bookkeeping).
    if scope is not None and scope.name == "langfuse-sdk":
        return True

    # 2. Known auto-instrumentation scopes — block.
    if scope is not None and scope.name in _BLOCKED_INSTRUMENTATION_SCOPES:
        return False

    # 3. ``backend.business`` tracer — allow by span name prefix whitelist.
    if scope is not None and scope.name == "backend.business":
        return any(span.name.startswith(prefix) for prefix in _ALLOWED_SPAN_PREFIXES)

    # 4. Any other tracer — block by default.
    return False
