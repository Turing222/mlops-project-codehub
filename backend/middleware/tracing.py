import logging
import time
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response, HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from ulid import ULID

# 这里的变量是“协程安全”的，每个请求都有自己独立的副本
REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="")

# 设置日志
logger = logging.getLogger(__name__)


def setup_tracing(app: FastAPI):
    @app.middleware("http")
    async def tracing_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # 1. 前置逻辑：生成/获取 RID
        rid = request.headers.get("X-Request-ID", str(ULID()))
        token = REQUEST_ID_CTX.set(rid)
        request.state.request_id = rid
        start_time = time.perf_counter()

        try:
            # 2. 核心：执行后续的路由逻辑
            response = await call_next(request)

            # 3. 后置逻辑：注入 Header 和记录日志
            process_time = (time.perf_counter() - start_time) * 1000
            response.headers["X-Request-ID"] = rid
            response.headers["X-Process-Time"] = f"{process_time:.2f}ms"

            logger.info(
                "Request Finished",
                extra={
                    "rid": rid,
                    "path": request.url.path,
                    "status": response.status_code,
                    "process_time_ms": round(process_time, 2),
                },
            )
            return response

        except Exception as e:
            logger.error("Request Failed", extra={"rid": rid, "error": str(e)})
            raise HTTPException(status_code=500, detail="Internal Server Error") from e
        finally:
            # 4. 必须执行：清理上下文，防止内存泄露或协程间干扰
            REQUEST_ID_CTX.reset(token)
