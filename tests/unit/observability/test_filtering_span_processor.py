"""Filtering span processor unit tests.

职责：验证 FilteringSpanProcessor 与 should_export_to_langfuse 过滤逻辑；边界：mock ReadableSpan，不连 Langfuse；副作用：无。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.util.instrumentation import InstrumentationScope

from backend.observability.filtering_span_processor import (
    FilteringSpanProcessor,
    should_export_to_langfuse,
)

# Helpers

def _make_span(
    name: str,
    scope_name: str | None = None,
) -> ReadableSpan:
    """Create a minimal ReadableSpan with the given name and instrumentation scope."""
    scope = InstrumentationScope(name=scope_name) if scope_name else None
    span = MagicMock(spec=ReadableSpan)
    span.name = name
    span.instrumentation_scope = scope
    return span

# should_export_to_langfuse

class TestShouldExportToLangfuse:
    """Unit tests for the span filter predicate."""

    # -- Langfuse SDK spans: always allowed --
    @pytest.mark.parametrize(
        "name",
        ["langfuse-generation", "langfuse-trace", "anything"],
    )
    def test_langfuse_sdk_span_always_allowed(self, name: str) -> None:
        span = _make_span(name, scope_name="langfuse-sdk")
        assert should_export_to_langfuse(span) is True

    # -- Auto-instrumentation scopes: always blocked --
    @pytest.mark.parametrize(
        "scope_name",
        [
            "opentelemetry.instrumentation.fastapi",
            "opentelemetry.instrumentation.sqlalchemy",
        ],
    )
    def test_auto_instrumentation_blocked(self, scope_name: str) -> None:
        span = _make_span("HTTP GET /v1/users/me", scope_name=scope_name)
        assert should_export_to_langfuse(span) is False

    # -- backend.business tracer: allowed prefixes --
    @pytest.mark.parametrize(
        "name",
        [
            "llm.pydantic_ai.stream",
            "llm.pydantic_ai.generate",
            "llm.mock.stream",
            "llm.mock.generate",
            "chat.context.build",
            "chat.context.retrieve_rag",
            "chat.stream.dispatch_task",
            "chat.stream.consume_worker_stream",
            "chat.stream.idempotency_check",
            "chat.stream.credit_precheck",
            "chat.stream.prepare_chat_context",
            "chat.stream.prepare_worker_payload",
            "chat.nonstream.dispatch_task",
            "chat.nonstream.idempotency_check",
            "chat.nonstream.credit_precheck",
            "chat.nonstream.prepare_chat_context",
            "chat.nonstream.prepare_worker_payload",
            "rag.retrieve.vector",
            "rag.retrieve.fulltext",
            "rag.retrieve.hybrid",
            "rag.rerank.retrieve_candidates",
            "rag.rerank.native",
            "rag.planner.generate",
            "embedding.openai_compatible.encode",
            "embedding.google_genai.encode",
            "embedding.google_genai.encode_batch",
            "rerank.bifrost",
            "rerank.dashscope",
            "vector_index.replace_file_chunks",
            "vector_index.search.vector",
            "vector_index.search.fulltext",
            "vector_index.search.hybrid",
            "knowledge.ingest.load_file",
            "knowledge.ingest.extract_chunks",
            "knowledge.ingest.index_chunks",
            "knowledge.upload.save_file",
            "knowledge.upload.create_task",
            "knowledge.upload.dispatch_task",
            "external_context.tavily.search",
            "repo_analysis.readme.collect",
            "taskiq.llm_stream.generate_and_publish",
            "taskiq.llm_nonstream.generate",
            "taskiq.llm_stream.prepare_context",
            "taskiq.llm_stream.rerank",
            "taskiq.knowledge.recover_stale_ingestions",
            "taskiq.knowledge.ingest.setup",
            "taskiq.knowledge.ingest.run",
            "taskiq.repo_analysis.readme.run",
        ],
    )
    def test_business_llm_spans_allowed(self, name: str) -> None:
        span = _make_span(name, scope_name="backend.business")
        assert should_export_to_langfuse(span) is True

    # -- backend.business tracer: blocked prefixes --
    @pytest.mark.parametrize(
        "name",
        [
            "http.rate_limit",
            "concurrency.llm",
            "concurrency.db",
        ],
    )
    def test_business_noise_spans_blocked(self, name: str) -> None:
        span = _make_span(name, scope_name="backend.business")
        assert should_export_to_langfuse(span) is False

    # -- Unknown tracer: blocked by default --
    def test_unknown_tracer_blocked(self) -> None:
        span = _make_span("some.span", scope_name="unknown.tracer")
        assert should_export_to_langfuse(span) is False

    # -- No instrumentation scope: blocked --
    def test_no_scope_blocked(self) -> None:
        span = _make_span("orphan.span", scope_name=None)
        assert should_export_to_langfuse(span) is False

# FilteringSpanProcessor

class TestFilteringSpanProcessor:
    """Unit tests for FilteringSpanProcessor."""

    @staticmethod
    def _make_processor(allow_fn):
        delegate = MagicMock()
        proc = FilteringSpanProcessor(delegate, allow_fn=allow_fn)
        return proc, delegate

    def test_on_start_always_delegated(self) -> None:
        allow_fn = MagicMock(return_value=False)
        proc, delegate = self._make_processor(allow_fn)
        span = _make_span("http.rate_limit", scope_name="backend.business")

        proc.on_start(span, parent_context=None)

        delegate.on_start.assert_called_once_with(span, None)
        allow_fn.assert_not_called()  # filter not evaluated at on_start

    def test_on_end_delegated_only_when_allowed(self) -> None:
        allow_fn = MagicMock(side_effect=lambda s: s.name.startswith("llm."))
        proc, delegate = self._make_processor(allow_fn)

        allowed_span = _make_span("llm.generate", scope_name="backend.business")
        blocked_span = _make_span("http.rate_limit", scope_name="backend.business")

        proc.on_end(allowed_span)
        proc.on_end(blocked_span)

        assert delegate.on_end.call_count == 1
        delegate.on_end.assert_called_once_with(allowed_span)

    def test_shutdown_always_delegated(self) -> None:
        proc, delegate = self._make_processor(lambda _: False)
        proc.shutdown()
        delegate.shutdown.assert_called_once()

    def test_force_flush_always_delegated(self) -> None:
        proc, delegate = self._make_processor(lambda _: False)
        delegate.force_flush.return_value = True
        result = proc.force_flush(timeout_millis=5000)
        delegate.force_flush.assert_called_once_with(5000)
        assert result is True
