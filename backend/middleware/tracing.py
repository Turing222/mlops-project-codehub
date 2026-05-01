import logging
import time

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from backend.core.trace_utils import (
    REQUEST_ID_CTX,
    current_trace_id,
    set_current_span_attributes,
)

# 设置日志
logger = logging.getLogger(__name__)


def setup_tracing(app: FastAPI):
    """
    简化版请求追踪中间件。

    OTel FastAPI Instrumentation 已自动处理：
    - span 创建与 trace_id 生成
    - 请求耗时测量（http.server.request.duration）
    - HTTP 指标采集

    本中间件仅负责：
    - 透传 Nginx 的 X-Request-ID 或使用 OTel trace_id 作为 RID
    - 注入 X-Request-ID / X-Trace-ID 响应头（方便前端 / 日志关联）
    - 将 RID 存入 ContextVar（供业务层使用）

    异常处理策略：
    - 中间件不负责生成错误响应，仅记录日志后 re-raise
    - 业务异常（AppException）和系统异常均由全局 exception_handler 统一处理
    """

    @app.middleware("http")
    async def tracing_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        trace_id = current_trace_id()

        # 1. 优先使用 Nginx 传入的 X-Request-ID，否则用 trace_id 作为 RID
        incoming_rid = request.headers.get("X-Request-ID", "").strip()
        rid = incoming_rid or trace_id
        token = REQUEST_ID_CTX.set(rid)
        request.state.request_id = rid
        request.state.trace_id = trace_id
        request.state.process_start = start
        set_current_span_attributes(
            {
                "app.request_id": rid,
                "app.incoming_request_id": bool(incoming_rid),
            }
        )

        try:
            # 2. 执行后续的路由逻辑（耗时由 OTel span 自动记录）
            response = await call_next(request)

            # 3. 注入关联 header
            process_time_ms = (time.perf_counter() - start) * 1000
            response.headers["X-Request-ID"] = rid
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Process-Time"] = f"{process_time_ms:.2f}ms"
            set_current_span_attributes(
                {
                    "app.request_id": rid,
                    "app.process_time_ms": process_time_ms,
                    "http.response.status_code": response.status_code,
                }
            )

            return response

        except Exception:
            # 仅记录日志，不自行构造响应
            # 异常交由全局 exception_handler 处理，确保业务异常（AppException）
            # 能走到正确的 handler，而不是被这里的兜底吞掉
            logger.debug(
                "Exception propagating through tracing middleware",
                extra={"rid": rid},
            )
            set_current_span_attributes(
                {"app.request_id": rid, "error.type": "exception"}
            )
            raise
        finally:
            # 4. 清理上下文，防止内存泄露或协程间干扰
            REQUEST_ID_CTX.reset(token)
