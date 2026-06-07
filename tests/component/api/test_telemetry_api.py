from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.deps import origin
from backend.api.v1.endpoint import telemetry_api
from backend.core.exception_handlers import setup_exception_handlers
from backend.middleware.tracing import setup_tracing

pytestmark = pytest.mark.component


@pytest.fixture
async def telemetry_client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    setup_exception_handlers(app)
    setup_tracing(app)
    app.include_router(telemetry_api.router, prefix="/api/v1/telemetry")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_frontend_error_telemetry_returns_204_and_logs_payload(
    telemetry_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=telemetry_api.__name__)

    response = await telemetry_client.post(
        "/api/v1/telemetry/errors",
        json={
            "message": "Internal Server Error",
            "status": 500,
            "errorCode": "server",
            "requestId": "api-req-123",
            "url": "/api/v1/users/me",
            "method": "GET",
            "source": "react_query",
        },
        headers={"X-Request-ID": "telemetry-req-1"},
    )

    assert response.status_code == 204
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "frontend_api_error"
    )
    assert record.telemetry_request_id == "telemetry-req-1"
    assert record.frontend_request_id == "api-req-123"
    assert record.frontend_status == 500
    assert record.frontend_error_code == "server"
    assert record.frontend_url == "/api/v1/users/me"


@pytest.mark.asyncio
async def test_frontend_error_telemetry_rejects_disallowed_origin(
    telemetry_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        origin.settings,
        "BACKEND_CORS_ORIGINS",
        ["https://admin.example.com"],
    )

    response = await telemetry_client.post(
        "/api/v1/telemetry/errors",
        json={
            "message": "Internal Server Error",
            "status": 500,
            "errorCode": "server",
            "requestId": "api-req-123",
        },
        headers={"Origin": "https://evil.example.com"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_frontend_error_telemetry_allows_forwarded_https_same_origin(
    telemetry_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(origin.settings, "BACKEND_CORS_ORIGINS", [])

    response = await telemetry_client.post(
        "/api/v1/telemetry/errors",
        json={
            "message": "Internal Server Error",
            "status": 500,
            "errorCode": "server",
            "requestId": "api-req-123",
        },
        headers={
            "Host": "admin.example.com",
            "Origin": "https://admin.example.com",
            "X-Forwarded-Proto": "https",
        },
    )

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_frontend_error_telemetry_rejects_empty_request_id(
    telemetry_client: AsyncClient,
) -> None:
    response = await telemetry_client.post(
        "/api/v1/telemetry/errors",
        json={
            "message": "Internal Server Error",
            "status": 500,
            "errorCode": "server",
            "requestId": "",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_frontend_error_telemetry_rejects_overlong_message(
    telemetry_client: AsyncClient,
) -> None:
    response = await telemetry_client.post(
        "/api/v1/telemetry/errors",
        json={
            "message": "x" * 501,
            "status": 500,
            "errorCode": "server",
            "requestId": "api-req-123",
        },
    )

    assert response.status_code == 422
