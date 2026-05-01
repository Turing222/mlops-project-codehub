"""Request tracing middleware.

职责：为每个 HTTP 请求绑定 request_id、trace_id 和响应头。
边界：OTel FastAPI instrumentation 负责 span 与指标，本模块只补充业务关联字段。
失败处理：异常继续交给全局 exception handler，避免中间件吞掉业务错误。
"""

import logging
import time

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from backend.observability.trace_utils import (
    REQUEST_ID_CTX,
    current_trace_id,
    set_current_span_attributes,
)

logger = logging.getLogger(__name__)


def setup_tracing(app: FastAPI) -> None:
    """注册 request_id/trace_id 关联中间件。"""

    @app.middleware("http")
    async def tracing_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        trace_id = current_trace_id()

        incoming_request_id = request.headers.get("X-Request-ID", "").strip()
        request_id = incoming_request_id or trace_id
        token = REQUEST_ID_CTX.set(request_id)
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request.state.process_start = start
        set_current_span_attributes(
            {
                "app.request_id": request_id,
                "app.incoming_request_id": bool(incoming_request_id),
            }
        )

        try:
            response = await call_next(request)

            process_time_ms = (time.perf_counter() - start) * 1000
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Process-Time"] = f"{process_time_ms:.2f}ms"
            set_current_span_attributes(
                {
                    "app.request_id": request_id,
                    "app.process_time_ms": process_time_ms,
                    "http.response.status_code": response.status_code,
                }
            )

            return response

        except Exception:
            # 这里只补充 trace 信息，错误响应统一由全局 exception handler 塑形。
            logger.debug(
                "Exception propagating through tracing middleware",
                extra={"request_id": request_id},
            )
            set_current_span_attributes(
                {"app.request_id": request_id, "error.type": "exception"}
            )
            raise
        finally:
            # 请求结束必须重置 ContextVar，避免协程复用时串 request_id。
            REQUEST_ID_CTX.reset(token)
