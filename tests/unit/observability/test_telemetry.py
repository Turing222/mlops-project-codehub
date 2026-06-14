"""Telemetry setup unit tests."""

from __future__ import annotations

from fastapi import FastAPI

from backend.observability import telemetry


def test_setup_telemetry_excludes_probe_urls(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_instrument_app(app: FastAPI, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    app = FastAPI()
    monkeypatch.setattr(telemetry.settings, "ENABLE_OTEL_TRACES", False)
    monkeypatch.setattr(telemetry.settings, "ENABLE_OTEL_METRICS", False)
    monkeypatch.setattr(
        telemetry.FastAPIInstrumentor,
        "instrument_app",
        fake_instrument_app,
    )
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: None)
    monkeypatch.setattr(telemetry.metrics, "set_meter_provider", lambda provider: None)

    telemetry.setup_telemetry(app)

    assert calls == [
        {
            "app": app,
            "excluded_urls": telemetry._EXCLUDED_FASTAPI_URLS,
        }
    ]
    assert "/api/v1/health_check/.*" in telemetry._EXCLUDED_FASTAPI_URLS
    assert "/v1/health_check/.*" in telemetry._EXCLUDED_FASTAPI_URLS
    assert "/metrics" in telemetry._EXCLUDED_FASTAPI_URLS
