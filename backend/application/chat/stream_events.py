"""Internal stream events for Worker-to-Web Redis channels.

职责：定义流式事件类型（内部通道 + Web SSE 共享），提供工厂与编解码函数。
边界：HTTP wire-format 序列化（encode_sse_event）留在 api.v1.sse_events；
      本模块只定义事件结构和内部通道编码。
"""

import json
from typing import Literal, TypedDict

# ---------------------------------------------------------------------------
# Internal Redis channel event types (Worker → Web)
# ---------------------------------------------------------------------------

StreamEventType = Literal["chunk", "error", "done", "meta", "started"]


class StreamEvent(TypedDict, total=False):
    """Normalized internal stream event."""

    type: StreamEventType
    content: str
    message: str


def stream_chunk_event(content: str) -> StreamEvent:
    return {"type": "chunk", "content": content}


def stream_error_event(message: str) -> StreamEvent:
    return {"type": "error", "message": message}


def stream_done_event() -> StreamEvent:
    return {"type": "done"}


def stream_started_event() -> StreamEvent:
    return {"type": "started"}


def encode_chunk_event(content: str) -> str:
    return json.dumps(stream_chunk_event(content), ensure_ascii=False)


def encode_error_event(message: str) -> str:
    return json.dumps(stream_error_event(message), ensure_ascii=False)


def encode_done_event() -> str:
    return json.dumps(stream_done_event(), ensure_ascii=False)


def encode_started_event() -> str:
    return json.dumps(stream_started_event(), ensure_ascii=False)


def encode_meta_event(
    *,
    session_id: str,
    session_title: str | None,
    message_id: str,
) -> str:
    return json.dumps(
        meta_event(
            session_id=session_id, session_title=session_title, message_id=message_id
        ),
        ensure_ascii=False,
    )


def decode_stream_event(payload: str) -> StreamEvent:
    """Decode structured events, accepting legacy raw payloads during rollout."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return _decode_legacy_payload(payload)

    if not isinstance(data, dict):
        return _decode_legacy_payload(payload)

    event_type = data.get("type")
    if event_type == "chunk":
        return stream_chunk_event(str(data.get("content") or ""))
    if event_type == "error":
        return stream_error_event(str(data.get("message") or ""))
    if event_type == "done":
        return stream_done_event()
    if event_type == "started":
        return stream_started_event()
    return _decode_legacy_payload(payload)


def _decode_legacy_payload(payload: str) -> StreamEvent:
    if payload == "[DONE]":
        return stream_done_event()
    if payload.startswith("[ERROR]"):
        return stream_error_event(payload[7:])
    return stream_chunk_event(payload)


# ---------------------------------------------------------------------------
# Web-facing SSE event types (shared by application + API layers)
# ---------------------------------------------------------------------------


class MetaEvent(TypedDict):
    """Chat stream metadata event."""

    type: Literal["meta"]
    session_id: str
    session_title: str | None
    message_id: str


class ChunkEvent(TypedDict):
    """Chat stream content chunk event."""

    type: Literal["chunk"]
    content: str


class ErrorEvent(TypedDict):
    """Chat stream error event."""

    type: Literal["error"]
    message: str


class DoneEvent(TypedDict):
    """Chat stream completion marker."""

    type: Literal["done"]


SSEEvent = MetaEvent | ChunkEvent | ErrorEvent | DoneEvent


def meta_event(
    *,
    session_id: str,
    session_title: str | None,
    message_id: str,
) -> MetaEvent:
    return {
        "type": "meta",
        "session_id": session_id,
        "session_title": session_title,
        "message_id": message_id,
    }


def chunk_event(content: str) -> ChunkEvent:
    return {"type": "chunk", "content": content}


def error_event(message: str) -> ErrorEvent:
    return {"type": "error", "message": message}


def done_event() -> DoneEvent:
    return {"type": "done"}
