"""Gen AI span attributes unit tests.

职责：验证 build_llm_span_attributes 输出结构；边界：纯函数调用，无外部 I/O；副作用：无。
"""

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
