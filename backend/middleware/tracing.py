import logging
import time
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from ulid import ULID

# 这里的变量是“协程安全”的，每个请求都有自己独立的副本
REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="")

# 设置日志
logger = logging.getLogger("uvicorn.error")


class TracingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        # 显式传递 app，这样类型检查器就能识别它是符合规格的 _MiddlewareFactory
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # 1. 获取 ID：优先从 Nginx Header 拿，拿不到就自造一个
        rid = request.headers.get("X-Request-ID", str(ULID()))

        # 2. 存入上下文，方便后续任何地方使用
        token = REQUEST_ID_CTX.set(rid)

        request.state.request_id = rid

        start_time = time.perf_counter()

        # 3. 执行后续逻辑（路由、数据库等）
        response = await call_next(request)

        # 4. 计算耗时
        end_time = time.perf_counter()
        process_time = (end_time - start_time) * 1000

        # 5. 把 ID 和耗时塞回 Response Header，让前端和 Nginx 也能看到
        response.headers["X-Request-ID"] = rid
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"

        # 打印一条总结性日志
        logger.info(
            f"Finished | RID: {rid} | Path: {request.url.path} | Time: {process_time:.2f}ms | Status: {response.status_code}"
        )
        # 清理上下文（好习惯，防止内存微量泄露）
        REQUEST_ID_CTX.reset(token)

        return response
