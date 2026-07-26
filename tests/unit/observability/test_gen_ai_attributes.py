"""Gen AI span attributes and content-safe exception telemetry unit tests.

职责：验证 build_llm_span_attributes 输出结构；边界：纯函数调用，无外部 I/O；副作用：无。
"""

from contextlib import contextmanager

import pytest

from backend.observability import trace_utils
from backend.observability.trace_utils import build_llm_span_attributes


def test_gen_ai_attributes_structure():
    attrs = build_llm_span_attributes(
        provider="openai-compatible",
        model="text-embedding-3-small",
        operation="embeddings",
    )
    assert attrs == {
        "gen_ai.system": "openai-compatible",
        "gen_ai.operation.name": "embeddings",
        "gen_ai.request.model": "text-embedding-3-small",
    }


def test_gen_ai_attributes_with_stream():
    attrs = build_llm_span_attributes(
        provider="gemini",
        model="gemini-2.0-flash",
        operation="generate",
        stream=True,
    )
    assert attrs["gen_ai.system"] == "gemini"
    assert attrs["gen_ai.operation.name"] == "generate"
    assert attrs["gen_ai.request.model"] == "gemini-2.0-flash"
    assert attrs["gen_ai.request.stream"] is True


def test_gen_ai_attributes_without_stream():
    attrs = build_llm_span_attributes(
        provider="mock",
        model="mock",
        operation="generate",
    )
    assert "gen_ai.request.stream" not in attrs


def test_trace_span_omits_exception_message_from_telemetry(monkeypatch) -> None:
    secret_marker = "provider-echo-AKIA1111111111111111-pii-13812345678"
    captured: dict[str, object] = {"events": []}

    class FakeSpan:
        def set_attribute(self, key: str, value: object) -> None:
            return None

        def add_event(self, name: str, attributes: dict[str, object]) -> None:
            captured["events"].append((name, attributes))  # type: ignore[union-attr]

        def set_status(self, status: object) -> None:
            captured["status"] = {
                "code": getattr(status, "status_code", None),
                "description": getattr(status, "description", None),
            }

    class FakeTracer:
        @contextmanager
        def start_as_current_span(self, _name: str):
            yield FakeSpan()

    monkeypatch.setattr(trace_utils, "_TRACER", FakeTracer())

    with (
        pytest.raises(RuntimeError, match="provider-echo"),
        trace_utils.trace_span("llm.test"),
    ):
        raise RuntimeError(secret_marker)

    telemetry = repr(captured)
    assert secret_marker not in telemetry
    assert "RuntimeError" in telemetry
    assert "operation_failed" in telemetry
