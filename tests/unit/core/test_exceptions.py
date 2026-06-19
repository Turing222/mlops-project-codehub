"""Exception handler unit tests.

职责：验证应用异常和兜底异常的 HTTP 响应结构；边界：使用进程内 ASGI 请求，不启动完整应用；副作用：无。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.core.exception_handlers import setup_exception_handlers
from backend.core.exceptions import app_not_found


@pytest.fixture
async def exception_client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/app-error")
    async def app_error(request: Request) -> None:
        request.state.request_id = "req-app"
        raise app_not_found("user missing", details={"username": "alice"})

    @app.get("/boom")
    async def boom(request: Request) -> None:
        request.state.request_id = "req-boom"
        raise RuntimeError("boom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_app_error_handler_returns_structured_payload(
    exception_client: AsyncClient,
) -> None:
    response = await exception_client.get("/app-error")

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "RESOURCE_NOT_FOUND",
        "message": "user missing",
        "details": {"username": "alice"},
        "request_id": "req-app",
    }


async def test_global_exception_handler_includes_request_id(
    exception_client: AsyncClient,
) -> None:
    response = await exception_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "INTERNAL_SERVER_ERROR",
        "message": "服务器内部错误",
        "details": {},
        "request_id": "req-boom",
    }
