"""Tracing middleware unit tests.

职责：验证 request id 传播、响应头和 contextvar 清理；边界：使用进程内 ASGI 请求，不连接外部观测系统；副作用：无。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.middleware.tracing import REQUEST_ID_CTX, setup_tracing


@pytest.fixture
async def tracing_client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    setup_tracing(app)

    @app.get("/inspect")
    async def inspect_request(request: Request) -> dict[str, str]:
        return {
            "state_request_id": request.state.request_id,
            "ctx_request_id": REQUEST_ID_CTX.get(),
        }

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_generates_request_id_and_process_time_in_headers(
    tracing_client: AsyncClient,
) -> None:
    response = await tracing_client.get("/inspect")

    assert response.status_code == 200

    request_id = response.headers["X-Request-ID"]
    body = response.json()

    assert request_id
    assert response.headers["X-Process-Time"].endswith("ms")
    assert body["state_request_id"] == request_id
    assert body["ctx_request_id"] == request_id
    assert REQUEST_ID_CTX.get() == ""


async def test_reuses_incoming_request_id_in_response_header(
    tracing_client: AsyncClient,
) -> None:
    response = await tracing_client.get("/inspect", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-123"

    body = response.json()
    assert body["state_request_id"] == "req-123"
    assert body["ctx_request_id"] == "req-123"
