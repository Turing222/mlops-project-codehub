# app/core/exceptions.py

from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
import logging
import traceback

# 获取我们在 setup_logging 中配置好的 logger
# 这里用 "uvicorn.error" 或者 __name__ 都可以，只要是根记录器的子集就能继承配置
logger = logging.getLogger(__name__)

def setup_exception_handlers(app: FastAPI):
    """
    配置全局异常处理
    """

    # 1. 捕获所有常规 Python 异常 (500 Internal Server Error)
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """
        当代码里抛出未处理的异常（如 1/0, KeyError）时触发
        """
        # 获取请求的详细信息，方便排查
        error_info = {
            "url": str(request.url),
            "method": request.method,
            "client_ip": request.client.host if request.client else "unknown",
            "error_msg": str(exc),
            # traceback.format_exc() 返回字符串形式的堆栈
            "traceback": traceback.format_exc() 
        }

        # 【核心步骤】记录 ERROR 级别的日志
        # exc_info=True 会自动把堆栈加入到 JSON 日志的 exception 字段中
        # extra=... 可以把 request 信息注入（需要 Logging 配置支持 extra，或者直接写在 msg 里）
        
        # 简单做法：直接拼接到 message 里，或者使用 structlog/loguru
        # 这里为了配合之前的 JSON Logger，我们手动构造一个字典传给 message 
        # (注意：标准库 logging 的 message 通常是字符串，但如果你配置了 JSON formatter 
        # 且做了特殊处理，可以传 dict。如果没有，建议用 f-string)
        
        logger.error(
            f"全局异常捕获: {request.method} {request.url} - {exc}",
            exc_info=True, # 关键！这会让错误堆栈写入 error.log
            extra=error_info # 如果你的 Formatter 支持 extra 字段，这很有用
        )

        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "message": "服务器内部错误，请联系管理员",
                "request_id": str(request.headers.get("x-request-id", "")) # 如果有 trace ID 最好带上
            },
        )

    # 2. (可选) 捕获特定的自定义异常
    # @app.exception_handler(MyCustomException)
    # ...



class AppError(Exception):
    """所有业务异常的基类"""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class ServiceError(AppError):
    """服务层发生的逻辑错误"""
    pass

class ValidationError(AppError):
    """数据校验失败"""
    pass
class DatabaseOperationError(AppError):
    """数据库操作失败"""
    pass

class FileParseException(AppError):
    """文件读取操作失败"""
    pass
