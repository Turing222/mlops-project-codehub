from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.middleware.tracing import REQUEST_ID_CTX, setup_tracing


@pytest.fixture
async def client():
    app = FastAPI()
    setup_tracing(app)

    @app.get("/inspect")
    async def inspect_request(request: Request):
        return {
            "state_request_id": request.state.request_id,
            "ctx_request_id": REQUEST_ID_CTX.get(),
        }

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_tracing_generates_request_id_and_process_time(client):
    response = await client.get("/inspect")

    assert response.status_code == 200

    request_id = response.headers["X-Request-ID"]
    body = response.json()

    assert request_id
    assert response.headers["X-Process-Time"].endswith("ms")
    assert body["state_request_id"] == request_id
    assert body["ctx_request_id"] == request_id
    assert REQUEST_ID_CTX.get() == ""


@pytest.mark.asyncio
async def test_tracing_reuses_incoming_request_id(client):
    response = await client.get("/inspect", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-123"

    body = response.json()
    assert body["state_request_id"] == "req-123"
    assert body["ctx_request_id"] == "req-123"
