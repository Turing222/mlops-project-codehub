"""Stream event encoding and decoding tests — typed payloads, round-trip, and legacy compatibility.

职责：验证流式事件的编码/解码往返、旧格式兼容和 HTTP SSE wire format；
边界：纯数据转换，不依赖外部服务；副作用：无。
"""

from backend.api.v1.sse_events import encode_sse_event
from backend.application.chat.stream_events import (
    chunk_event,
    decode_stream_event,
    done_event,
    encode_chunk_event,
    encode_done_event,
    encode_error_event,
    encode_started_event,
    error_event,
    meta_event,
    stream_chunk_event,
    stream_done_event,
    stream_error_event,
    stream_started_event,
)


def test_stream_event_helpers_build_typed_payloads() -> None:
    assert stream_chunk_event("hello") == {"type": "chunk", "content": "hello"}
    assert stream_error_event("failed") == {"type": "error", "message": "failed"}
    assert stream_done_event() == {"type": "done"}
    assert stream_started_event() == {"type": "started"}


def test_stream_events_round_trip_structured_payloads() -> None:
    assert decode_stream_event(encode_chunk_event("hello")) == {
        "type": "chunk",
        "content": "hello",
    }
    assert decode_stream_event(encode_error_event("failed")) == {
        "type": "error",
        "message": "failed",
    }
    assert decode_stream_event(encode_done_event()) == {"type": "done"}
    assert decode_stream_event(encode_started_event()) == {"type": "started"}


def test_stream_events_accept_legacy_payloads() -> None:
    assert decode_stream_event("raw chunk") == {
        "type": "chunk",
        "content": "raw chunk",
    }
    assert decode_stream_event("[ERROR]failed") == {
        "type": "error",
        "message": "failed",
    }
    assert decode_stream_event("[DONE]") == {"type": "done"}


def test_http_sse_event_helpers_build_typed_payloads() -> None:
    assert meta_event(
        session_id="session-1",
        session_title="demo",
        message_id="message-1",
    ) == {
        "type": "meta",
        "session_id": "session-1",
        "session_title": "demo",
        "message_id": "message-1",
    }
    assert chunk_event("hello") == {"type": "chunk", "content": "hello"}
    assert error_event("failed") == {"type": "error", "message": "failed"}
    assert done_event() == {"type": "done"}


def test_http_sse_events_keep_existing_wire_format() -> None:
    assert (
        encode_sse_event(
            meta_event(
                session_id="session-1",
                session_title="demo",
                message_id="message-1",
            )
        )
        == 'data: {"type": "meta", "session_id": "session-1", '
        '"session_title": "demo", "message_id": "message-1"}\n\n'
    )
    assert encode_sse_event(chunk_event("hello")) == (
        'data: {"type": "chunk", "content": "hello"}\n\n'
    )
    assert encode_sse_event(done_event()) == "data: [DONE]\n\n"
