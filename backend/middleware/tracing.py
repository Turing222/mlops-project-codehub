import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# 这里的变量是“协程安全”的，每个请求都有自己独立的副本
REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="")

# 设置日志
logger = logging.getLogger("uvicorn.error")


class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. 获取 ID：优先从 Nginx Header 拿，拿不到就自造一个
        rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # 2. 存入上下文，方便后续任何地方使用
        token = REQUEST_ID_CTX.set(rid)

        start_time = time.time()

        try:
            # 3. 执行后续逻辑（路由、数据库等）
            response = await call_next(request)

        except Exception as e:
            # 4. 兜底逻辑：如果后端代码崩了，这里确保返回 JSON 而不是断开连接
            logger.error(
                f"Critical Error | RID: {rid} | Error: {str(e)}", exc_info=True
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error", "request_id": rid},
            )

        finally:
            # 5. 计算耗时
            process_time = (time.time() - start_time) * 1000

            # 6. 把 ID 和耗时塞回 Response Header，让前端和 Nginx 也能看到
            response.headers["X-Request-ID"] = rid
            response.headers["X-Process-Time"] = f"{process_time:.2f}ms"

            # 打印一条总结性日志
            logger.info(
                f"Finished | RID: {rid} | Path: {request.url.path} | Time: {process_time:.2f}ms | Status: {response.status_code}"
            )

            # 清理上下文（好习惯，防止内存微量泄露）
            REQUEST_ID_CTX.reset(token)

        return response
