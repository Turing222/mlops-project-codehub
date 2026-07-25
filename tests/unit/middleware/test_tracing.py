"""Tracing middleware unit tests.

职责：验证 request id 传播、响应头和 contextvar 清理；边界：使用进程内 ASGI 请求，不连接外部观测系统；副作用：无。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request, Response
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

    @app.get("/fail/{item_id}")
    async def fail_request(item_id: str) -> Response:
        return Response(status_code=503, headers={"X-Test-Item": item_id})

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


async def test_logs_stable_5xx_fields_without_query_content(
    tracing_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    query_marker = "query-secret-AKIA1111111111111111"
    caplog.set_level("INFO", logger="backend.middleware.tracing")

    response = await tracing_client.get(
        f"/fail/record-1?query={query_marker}",
        headers={"X-Request-ID": "request-503"},
    )

    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "api_request_completed"
    )
    assert response.status_code == 503
    assert record.http_request_id == "request-503"
    assert record.route == "/fail/{item_id}"
    assert record.status_code == 503
    assert record.error_code == "HTTP_503"
    assert isinstance(record.duration_ms, float)
    assert query_marker not in repr(record.__dict__)
