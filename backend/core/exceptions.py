# app/core/exceptions.py

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# 获取我们在 setup_logging 中配置好的 logger
# 这里用 "uvicorn.error" 或者 __name__ 都可以，只要是根记录器的子集就能继承配置
logger = logging.getLogger(__name__)


def setup_exception_handlers(app: FastAPI):

    # --- 1. 处理业务异常 (AppError 系列) ---
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        # 直接从异常对象获取状态码，不再写 if-else
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request.state.request_id,  # 关联中间件生成的 ID
            },
        )

    # --- 2. 处理意料之外的系统异常 (真正的 Bug) ---
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # 如果走到这一步，说明是没捕获的 1/0, AttributeError 等
        # 这里才需要记录 exc_info=True (堆栈)
        logger.error(f"系统崩溃: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "message": "服务器开小差了",
                "request_id": request.state.request_id,
            },
        )


# ---  定义异常类 (Domain Layer) ---


class AppError(Exception):
    """所有业务异常的基类"""

    status_code = 400  # 默认 400

    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(AppError):
    """参数校验失败"""

    status_code = 422


class ResourceNotFound(AppError):
    """资源不存在"""

    status_code = 404


class FileParseException(AppError):
    """文件读取操作失败"""

    status_code = 403


class ServiceError(AppError):
    """服务层发生的逻辑错误"""

    status_code = 501


class DatabaseOperationError(AppError):
    """数据库操作失败"""

    status_code = 502


class DatabaseConnectionError(AppError):
    """DBA 专属：数据库挂了"""

    status_code = 503
