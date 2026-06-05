"""Main startup unit tests.

职责：验证 main 导入副作用和 lifespan 启停顺序；边界：使用 monkeypatch 替换外部初始化，不连接真实 DB/Redis；副作用：临时刷新 backend.main 模块。
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest


def _fresh_main_module() -> Any:
    sys.modules.pop("backend.main", None)
    return importlib.import_module("backend.main")


def test_importing_main_does_not_setup_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_setup_logging() -> None:
        calls.append("setup")

    monkeypatch.setattr(
        "backend.observability.logger.setup_logging", fake_setup_logging
    )

    _fresh_main_module()

    assert calls == []


def test_production_disables_public_api_docs() -> None:
    main = _fresh_main_module()

    assert main._api_docs_urls("prod") == (None, None, None)


def test_non_production_keeps_public_api_docs() -> None:
    main = _fresh_main_module()

    assert main._api_docs_urls("test") == ("/docs", "/redoc", "/openapi.json")


@pytest.mark.asyncio
async def test_lifespan_sets_up_logging_first(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    main = _fresh_main_module()

    @asynccontextmanager
    async def fake_init_db(app: object) -> AsyncIterator[None]:
        events.append("db")
        yield

    async def fake_redis_init() -> None:
        events.append("redis_init")

    async def fake_redis_close() -> None:
        events.append("redis_close")

    monkeypatch.setattr(main, "setup_logging", lambda: events.append("logging"))
    monkeypatch.setattr(main, "get_permission_policy", lambda: events.append("policy"))
    monkeypatch.setattr(main, "validate_llm_configs", lambda: events.append("llm"))
    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(
        main,
        "redis_client",
        SimpleNamespace(init=fake_redis_init, close=fake_redis_close),
    )
    monkeypatch.setattr(main, "shutdown_telemetry", lambda: events.append("shutdown"))

    async with main.lifespan(SimpleNamespace()):
        events.append("yielded")

    assert events == [
        "logging",
        "policy",
        "llm",
        "db",
        "redis_init",
        "yielded",
        "redis_close",
        "shutdown",
    ]
