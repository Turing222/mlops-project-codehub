"""Application exception boundary.

职责：定义统一业务异常和 FastAPI 全局异常处理器。
边界：本模块只塑形 HTTP 错误响应，不负责业务补偿或日志上下文生成。
副作用：处理器会透传 request_id/trace_id 响应头，便于前端和日志关联。
"""

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _trace_response_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    request_id = getattr(request.state, "request_id", None)
    trace_id = getattr(request.state, "trace_id", None)
    process_start = getattr(request.state, "process_start", None)

    if request_id:
        headers["X-Request-ID"] = str(request_id)
    if trace_id:
        headers["X-Trace-ID"] = str(trace_id)
    if isinstance(process_start, int | float):
        headers["X-Process-Time"] = (
            f"{(time.perf_counter() - process_start) * 1000:.2f}ms"
        )
    return headers


def setup_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，保持错误响应结构一致。"""

    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request,
        exc: AppException,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)

        logger.warning(
            "AppException: code=%s message=%s request_id=%s",
            exc.code,
            exc.message,
            request_id,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(
                {
                    "error_code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                }
            ),
            headers=_trace_response_headers(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        detail = exc.detail

        logger.warning(
            "HTTPException: status_code=%s detail=%s request_id=%s",
            exc.status_code,
            detail,
            request_id,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(
                {
                    "error_code": f"HTTP_{exc.status_code}",
                    "message": detail if isinstance(detail, str) else "请求失败",
                    "details": detail if isinstance(detail, dict) else {},
                    "request_id": request_id,
                }
            ),
            headers={
                **_trace_response_headers(request),
                **(getattr(exc, "headers", None) or {}),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)

        logger.warning(
            "RequestValidationError: request_id=%s errors=%s",
            request_id,
            exc.errors(),
        )

        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                {
                    "error_code": "REQUEST_VALIDATION_ERROR",
                    "message": "请求参数校验失败",
                    "details": {"errors": exc.errors()},
                    "request_id": request_id,
                }
            ),
            headers=_trace_response_headers(request),
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)

        logger.exception(
            "Unexpected exception: type=%s request_id=%s",
            exc.__class__.__name__,
            request_id,
        )

        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "服务器内部错误",
                "details": {},
                "request_id": request_id,
            },
            headers=_trace_response_headers(request),
        )


class AppException(Exception):
    """可映射为统一 HTTP 错误响应的业务异常。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def app_bad_request(
    message: str,
    *,
    code: str = "BAD_REQUEST",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 400 Bad Request 业务异常。"""
    return AppException(code=code, message=message, status_code=400, details=details)


def app_validation_error(
    message: str,
    *,
    code: str = "VALIDATION_ERROR",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 422 Validation Error 业务异常。"""
    return AppException(code=code, message=message, status_code=422, details=details)


def app_unauthorized(
    message: str,
    *,
    code: str = "UNAUTHORIZED",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 401 Unauthorized 业务异常。"""
    return AppException(code=code, message=message, status_code=401, details=details)


def app_forbidden(
    message: str,
    *,
    code: str = "PERMISSION_DENIED",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 403 Forbidden 业务异常。"""
    return AppException(code=code, message=message, status_code=403, details=details)


def app_not_found(
    message: str,
    *,
    code: str = "RESOURCE_NOT_FOUND",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 404 Not Found 业务异常。"""
    return AppException(code=code, message=message, status_code=404, details=details)


def app_payload_too_large(
    message: str,
    *,
    code: str = "PAYLOAD_TOO_LARGE",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 413 Payload Too Large 业务异常。"""
    return AppException(code=code, message=message, status_code=413, details=details)


def app_too_many_requests(
    message: str,
    *,
    code: str = "TOO_MANY_REQUESTS",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 429 Too Many Requests 业务异常。"""
    return AppException(code=code, message=message, status_code=429, details=details)


def app_service_error(
    message: str,
    *,
    code: str = "SERVICE_ERROR",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 500 Service Error 业务异常。"""
    return AppException(code=code, message=message, status_code=500, details=details)


def app_dependency_unavailable(
    message: str,
    *,
    code: str = "DEPENDENCY_UNAVAILABLE",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 503 Dependency Unavailable 业务异常。"""
    return AppException(code=code, message=message, status_code=503, details=details)
