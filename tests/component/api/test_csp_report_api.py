"""CSP report API component tests.

职责：验证 CSP 上报端点的 ASGI 装配与请求/响应序列化；边界：用 dependency override 与 ASGITransport，不连真实下游；副作用：无。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.deps import origin
from backend.api.v1 import api as v1_api
from backend.api.v1.endpoint import csp_report_api
from backend.core.exception_handlers import setup_exception_handlers
from backend.middleware.tracing import setup_tracing

pytestmark = pytest.mark.component


@pytest.fixture
async def csp_report_client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    setup_exception_handlers(app)
    setup_tracing(app)
    app.include_router(csp_report_api.router, prefix="/api/v1/csp")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _csp_payload(**overrides: object) -> dict[str, object]:
    report = {
        "document-uri": "https://app.example.com/dashboard",
        "blocked-uri": "https://cdn.example.net/script.js",
        "violated-directive": "script-src-elem",
        "effective-directive": "script-src-elem",
        "source-file": "https://app.example.com/assets/app.js",
        "line-number": 42,
        "disposition": "report",
    }
    report.update(overrides)
    return {"csp-report": report}


async def test_csp_report_returns_204_and_logs_payload(
    csp_report_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=csp_report_api.__name__)

    response = await csp_report_client.post(
        "/api/v1/csp/reports",
        json=_csp_payload(),
        headers={"X-Request-ID": "csp-req-1"},
    )

    assert response.status_code == 204
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "csp_violation"
    )
    assert record.telemetry_request_id == "csp-req-1"
    assert record.document_uri == "https://app.example.com/dashboard"
    assert record.blocked_uri == "https://cdn.example.net/script.js"
    assert record.violated_directive == "script-src-elem"
    assert record.effective_directive == "script-src-elem"
    assert record.source_file == "https://app.example.com/assets/app.js"
    assert record.line_number == 42
    assert record.disposition == "report"


async def test_csp_report_accepts_csp_report_content_type(
    csp_report_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=csp_report_api.__name__)

    response = await csp_report_client.post(
        "/api/v1/csp/reports",
        content='{"csp-report":{"blocked-uri":"inline","disposition":"report"}}',
        headers={"Content-Type": "application/csp-report"},
    )

    assert response.status_code == 204
    assert any(
        getattr(item, "event", None) == "csp_violation" for item in caplog.records
    )


async def test_csp_report_accepts_zero_line_number(
    csp_report_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=csp_report_api.__name__)

    response = await csp_report_client.post(
        "/api/v1/csp/reports",
        json=_csp_payload(**{"line-number": 0}),
    )

    assert response.status_code == 204
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "csp_violation"
    )
    assert record.line_number == 0


async def test_csp_report_rejects_disallowed_origin(
    csp_report_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        origin.settings,
        "BACKEND_CORS_ORIGINS",
        ["https://admin.example.com"],
    )

    response = await csp_report_client.post(
        "/api/v1/csp/reports",
        json=_csp_payload(),
        headers={"Origin": "https://evil.example.com"},
    )

    assert response.status_code == 403


async def test_csp_report_allows_forwarded_https_same_origin(
    csp_report_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        origin.settings,
        "BACKEND_CORS_ORIGINS",
        [],
    )

    response = await csp_report_client.post(
        "/api/v1/csp/reports",
        json=_csp_payload(),
        headers={
            "Host": "admin.example.com",
            "Origin": "https://admin.example.com",
            "X-Forwarded-Proto": "https",
        },
    )

    assert response.status_code == 204


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"blocked-uri": "https://cdn.example.net/script.js"},
    ],
)
async def test_csp_report_rejects_missing_report_envelope(
    csp_report_client: AsyncClient,
    payload: dict[str, object],
) -> None:
    response = await csp_report_client.post("/api/v1/csp/reports", json=payload)

    assert response.status_code == 422


async def test_csp_report_rejects_overlong_field(
    csp_report_client: AsyncClient,
) -> None:
    response = await csp_report_client.post(
        "/api/v1/csp/reports",
        json=_csp_payload(**{"blocked-uri": "x" * 2049}),
    )

    assert response.status_code == 422


def test_csp_report_router_is_mounted_under_api_v1() -> None:
    app = FastAPI()
    app.dependency_overrides[v1_api.csp_report_limiter] = lambda: None
    app.include_router(v1_api.api_router, prefix="/api/v1")

    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/api/v1/csp/reports" in paths
