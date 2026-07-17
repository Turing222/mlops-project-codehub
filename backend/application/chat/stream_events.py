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

StreamEventType = Literal["chunk", "error", "done", "meta", "started", "step"]

StepStatus = Literal["running", "done", "skipped"]


class StreamEvent(TypedDict, total=False):
    """Normalized internal stream event."""

    type: StreamEventType
    content: str
    message: str
    step: str
    status: StepStatus
    metrics: dict[str, object]
    error_code: str
    retryable: bool


def stream_chunk_event(content: str) -> StreamEvent:
    return {"type": "chunk", "content": content}


def stream_error_event(
    message: str,
    *,
    error_code: str | None = None,
    retryable: bool | None = None,
) -> StreamEvent:
    event: StreamEvent = {"type": "error", "message": message}
    if error_code is not None:
        event["error_code"] = error_code
    if retryable is not None:
        event["retryable"] = retryable
    return event


def stream_done_event() -> StreamEvent:
    return {"type": "done"}


def stream_started_event() -> StreamEvent:
    return {"type": "started"}


def stream_step_event(
    step: str,
    status: StepStatus,
    metrics: dict[str, object] | None = None,
) -> StreamEvent:
    event: StreamEvent = {"type": "step", "step": step, "status": status}
    if metrics:
        event["metrics"] = metrics
    return event


def encode_chunk_event(content: str) -> str:
    return json.dumps(stream_chunk_event(content), ensure_ascii=False)


def encode_error_event(
    message: str,
    *,
    error_code: str | None = None,
    retryable: bool | None = None,
) -> str:
    return json.dumps(
        stream_error_event(
            message,
            error_code=error_code,
            retryable=retryable,
        ),
        ensure_ascii=False,
    )


def encode_done_event() -> str:
    return json.dumps(stream_done_event(), ensure_ascii=False)


def encode_started_event() -> str:
    return json.dumps(stream_started_event(), ensure_ascii=False)


def encode_step_event(
    *,
    step: str,
    status: StepStatus,
    metrics: dict[str, object] | None = None,
) -> str:
    return json.dumps(
        stream_step_event(step, status, metrics),
        ensure_ascii=False,
    )


def encode_meta_event(
    *,
    session_id: str,
    session_title: str | None,
    message_id: str,
    generation_request_id: str | None = None,
    attempt: int | None = None,
) -> str:
    return json.dumps(
        meta_event(
            session_id=session_id,
            session_title=session_title,
            message_id=message_id,
            generation_request_id=generation_request_id,
            attempt=attempt,
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
        error_code = data.get("error_code")
        retryable = data.get("retryable")
        return stream_error_event(
            str(data.get("message") or ""),
            error_code=str(error_code) if error_code else None,
            retryable=retryable if isinstance(retryable, bool) else None,
        )
    if event_type == "done":
        return stream_done_event()
    if event_type == "started":
        return stream_started_event()
    if event_type == "step":
        status = data.get("status")
        if status not in {"running", "done", "skipped"}:
            status = "running"
        metrics = data.get("metrics")
        return stream_step_event(
            str(data.get("step") or ""),
            status,
            metrics if isinstance(metrics, dict) else None,
        )
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


class MetaEvent(TypedDict, total=False):
    """Chat stream metadata event."""

    type: Literal["meta"]
    session_id: str
    session_title: str | None
    message_id: str
    generation_request_id: str
    attempt: int


class ChunkEvent(TypedDict):
    """Chat stream content chunk event."""

    type: Literal["chunk"]
    content: str


class ErrorEvent(TypedDict, total=False):
    """Chat stream error event."""

    type: Literal["error"]
    message: str
    error_code: str
    retryable: bool
    generation_request_id: str
    attempt: int


class DoneEvent(TypedDict):
    """Chat stream completion marker."""

    type: Literal["done"]


class StepEvent(TypedDict, total=False):
    """Agent trace step progress event."""

    type: Literal["step"]
    step: str
    status: StepStatus
    metrics: dict[str, object]


SSEEvent = MetaEvent | ChunkEvent | ErrorEvent | DoneEvent | StepEvent


def meta_event(
    *,
    session_id: str,
    session_title: str | None,
    message_id: str,
    generation_request_id: str | None = None,
    attempt: int | None = None,
) -> MetaEvent:
    event: MetaEvent = {
        "type": "meta",
        "session_id": session_id,
        "session_title": session_title,
        "message_id": message_id,
    }
    if generation_request_id is not None:
        event["generation_request_id"] = generation_request_id
    if attempt is not None:
        event["attempt"] = attempt
    return event


def chunk_event(content: str) -> ChunkEvent:
    return {"type": "chunk", "content": content}


def error_event(
    message: str,
    *,
    error_code: str | None = None,
    retryable: bool | None = None,
    generation_request_id: str | None = None,
    attempt: int | None = None,
) -> ErrorEvent:
    event: ErrorEvent = {"type": "error", "message": message}
    if error_code is not None:
        event["error_code"] = error_code
    if retryable is not None:
        event["retryable"] = retryable
    if generation_request_id is not None:
        event["generation_request_id"] = generation_request_id
    if attempt is not None:
        event["attempt"] = attempt
    return event


def done_event() -> DoneEvent:
    return {"type": "done"}


def step_event(
    *,
    step: str,
    status: StepStatus,
    metrics: dict[str, object] | None = None,
) -> StepEvent:
    event: StepEvent = {"type": "step", "step": step, "status": status}
    if metrics:
        event["metrics"] = metrics
    return event
