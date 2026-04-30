from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.core.exceptions import app_not_found, setup_exception_handlers
from backend.middleware.tracing import setup_tracing


@pytest.fixture
async def client():
    app = FastAPI()
    setup_exception_handlers(app)
    setup_tracing(app)

    @app.get("/app-error")
    async def app_error():
        raise app_not_found("user missing", details={"username": "alice"})

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_tracing_and_app_error_share_same_request_id(client):
    response = await client.get("/app-error", headers={"X-Request-ID": "req-404"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "req-404"
    assert response.headers["X-Process-Time"].endswith("ms")
    assert response.json() == {
        "error_code": "RESOURCE_NOT_FOUND",
        "message": "user missing",
        "details": {"username": "alice"},
        "request_id": "req-404",
    }


@pytest.mark.asyncio
async def test_tracing_and_global_exception_generate_traceable_500(client):
    response = await client.get("/boom")

    assert response.status_code == 500

    request_id = response.headers["X-Request-ID"]
    assert request_id
    assert response.headers["X-Process-Time"].endswith("ms")
    assert response.json() == {
        "error_code": "INTERNAL_SERVER_ERROR",
        "message": "服务器内部错误",
        "details": {},
        "request_id": request_id,
    }
