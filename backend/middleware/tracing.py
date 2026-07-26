"""Request tracing middleware.

职责：为每个 HTTP 请求绑定 request_id、trace_id 和响应头。
边界：OTel FastAPI instrumentation 负责 span 与指标，本模块只补充业务关联字段。
失败处理：异常继续交给全局 exception handler，避免中间件吞掉业务错误。

使用原生 ASGI 中间件而非 BaseHTTPMiddleware，
避免 SSE 流式响应下 receive 链被干扰导致流中断。
"""

import logging
import time

from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.observability.trace_utils import (
    REQUEST_ID_CTX,
    current_trace_id,
    set_current_span_attributes,
)

logger = logging.getLogger(__name__)


class TracingMiddleware:
    """为每个 HTTP 请求绑定 request_id / trace_id 并注入响应头。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        trace_id = current_trace_id()

        headers = dict(scope.get("headers", []))
        incoming_request_id = headers.get(b"x-request-id", b"").decode().strip()
        request_id = incoming_request_id or trace_id
        token = REQUEST_ID_CTX.set(request_id)

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id
        scope["state"]["trace_id"] = trace_id
        scope["state"]["process_start"] = start
        response_logged = False

        set_current_span_attributes(
            {
                "app.incoming_request_id": bool(incoming_request_id),
            }
        )

        async def send_with_headers(message: dict) -> None:
            nonlocal response_logged
            if message["type"] == "http.response.start":
                process_time_ms = (time.perf_counter() - start) * 1000
                status_code = int(message["status"])
                headers_list = [
                    h
                    for h in message.get("headers", [])
                    if h[0].lower()
                    not in (b"x-request-id", b"x-trace-id", b"x-process-time")
                ]
                headers_list.append([b"x-request-id", request_id.encode()])
                headers_list.append([b"x-trace-id", trace_id.encode()])
                headers_list.append(
                    [b"x-process-time", f"{process_time_ms:.2f}ms".encode()]
                )
                message = {**message, "headers": headers_list}
                set_current_span_attributes(
                    {
                        "app.request_id": request_id,
                        "app.process_time_ms": process_time_ms,
                        "http.response.status_code": status_code,
                    }
                )
                route = getattr(scope.get("route"), "path", None)
                event_fields: dict[str, object] = {
                    "event": "api_request_completed",
                    "http_request_id": request_id,
                    "method": str(scope.get("method") or ""),
                    "route": str(route or scope.get("path") or ""),
                    "status_code": status_code,
                    "duration_ms": round(process_time_ms, 3),
                }
                if status_code >= 500:
                    event_fields["error_code"] = f"HTTP_{status_code}"
                logger.log(
                    logging.ERROR if status_code >= 500 else logging.INFO,
                    "API request completed",
                    extra=event_fields,
                )
                response_logged = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)  # type: ignore[arg-type]
        except Exception:
            if not response_logged:
                logger.error(
                    "API request failed before a response started",
                    extra={
                        "event": "api_request_completed",
                        "error_code": "UNHANDLED_API_EXCEPTION",
                        "http_request_id": request_id,
                        "method": str(scope.get("method") or ""),
                        "route": str(scope.get("path") or ""),
                        "status_code": 500,
                        "duration_ms": round(
                            (time.perf_counter() - start) * 1000,
                            3,
                        ),
                    },
                )
            set_current_span_attributes(
                {"app.request_id": request_id, "error.type": "exception"}
            )
            raise
        finally:
            REQUEST_ID_CTX.reset(token)


def setup_tracing(app: FastAPI) -> None:
    """Helper to add TracingMiddleware to a FastAPI application."""
    app.add_middleware(TracingMiddleware)  # type: ignore[arg-type]
