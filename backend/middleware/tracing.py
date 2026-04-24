import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry import trace
from starlette.middleware.base import RequestResponseEndpoint

# 保留 ContextVar 以便业务层获取 RID（如日志、异常报告等）
REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="")

# 设置日志
logger = logging.getLogger(__name__)


def _current_trace_id() -> str:
    span = trace.get_current_span()
    span_ctx = span.get_span_context()
    if span_ctx and span_ctx.trace_id:
        return f"{span_ctx.trace_id:032x}"
    return uuid.uuid4().hex


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
    """

    @app.middleware("http")
    async def tracing_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        trace_id = _current_trace_id()

        # 1. 优先使用 Nginx 传入的 X-Request-ID，否则用 trace_id 作为 RID
        incoming_rid = request.headers.get("X-Request-ID", "").strip()
        rid = incoming_rid or trace_id
        token = REQUEST_ID_CTX.set(rid)
        request.state.request_id = rid

        try:
            # 2. 执行后续的路由逻辑（耗时由 OTel span 自动记录）
            response = await call_next(request)

            # 3. 注入关联 header
            response.headers["X-Request-ID"] = rid
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Process-Time"] = (
                f"{(time.perf_counter() - start) * 1000:.2f}ms"
            )

            return response

        except Exception as e:
            logger.error("Request Failed", extra={"rid": rid, "error": str(e)})
            return JSONResponse(
                status_code=500,
                content={
                    "message": "服务器开小差了",
                    "request_id": rid,
                },
                headers={
                    "X-Request-ID": rid,
                    "X-Trace-ID": trace_id,
                    "X-Process-Time": f"{(time.perf_counter() - start) * 1000:.2f}ms",
                },
            )
        finally:
            # 4. 清理上下文，防止内存泄露或协程间干扰
            REQUEST_ID_CTX.reset(token)
