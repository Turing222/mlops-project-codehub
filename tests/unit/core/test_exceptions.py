from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.core.exceptions import ResourceNotFound, setup_exception_handlers


@pytest.fixture
async def client():
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/app-error")
    async def app_error(request: Request):
        request.state.request_id = "req-app"
        raise ResourceNotFound("user missing", {"username": "alice"})

    @app.get("/boom")
    async def boom(request: Request):
        request.state.request_id = "req-boom"
        raise RuntimeError("boom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_app_error_handler_returns_structured_payload(client):
    response = await client.get("/app-error")

    assert response.status_code == 404
    assert response.json() == {
        "code": 404,
        "message": "user missing",
        "details": {"username": "alice"},
        "request_id": "req-app",
    }


@pytest.mark.asyncio
async def test_global_exception_handler_includes_request_id(client):
    response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "message": "服务器开小差了",
        "request_id": "req-boom",
    }
