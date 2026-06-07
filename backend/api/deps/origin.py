"""Shared request origin checks for browser-originated ingestion endpoints.

职责：为浏览器来源的 ingestion 端点做同源与 CORS allowlist 校验。
边界：本模块不做鉴权、不落库，也不承担业务请求的通用访问控制。
"""

from fastapi import Request

from backend.config.settings import settings


def is_allowed_browser_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True

    configured_origins = {
        str(item).rstrip("/") for item in settings.BACKEND_CORS_ORIGINS
    }
    if "*" in configured_origins or origin.rstrip("/") in configured_origins:
        return True

    host = request.headers.get("host")
    if host:
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        scheme = forwarded_proto.split(",", maxsplit=1)[0].strip() or request.url.scheme
        same_origin = f"{scheme}://{host}".rstrip("/")
        return origin.rstrip("/") == same_origin

    return False
