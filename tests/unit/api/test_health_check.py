"""Health check endpoint unit tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from opentelemetry.instrumentation.utils import is_instrumentation_enabled

from backend.api.v1.endpoint.health_check import readiness_check


class FakeConnection:
    def __init__(self) -> None:
        self.instrumentation_enabled_during_execute: bool | None = None

    async def execute(self, _statement: object) -> None:
        self.instrumentation_enabled_during_execute = is_instrumentation_enabled()


class FakeConnectionContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.instrumentation_enabled_during_enter: bool | None = None

    async def __aenter__(self) -> FakeConnection:
        self.instrumentation_enabled_during_enter = is_instrumentation_enabled()
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakePool:
    def status(self) -> str:
        return "ok"


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.connection_context = FakeConnectionContext(self.connection)
        self.pool = FakePool()

    def connect(self) -> FakeConnectionContext:
        return self.connection_context


@pytest.mark.asyncio
async def test_readiness_check_suppresses_db_instrumentation() -> None:
    engine = FakeEngine()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_engine=engine))
    )

    response = await readiness_check(request)  # type: ignore[arg-type]

    assert response["status"] == "ready"
    assert engine.connection_context.instrumentation_enabled_during_enter is False
    assert engine.connection.instrumentation_enabled_during_execute is False
