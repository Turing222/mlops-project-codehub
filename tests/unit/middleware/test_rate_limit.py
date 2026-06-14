"""Rate limit middleware unit tests.

职责：验证限流依赖的允许、拒绝和 Redis 成员生成行为；边界：使用 fake Redis 和进程内 ASGI 请求，不连接真实 Redis；副作用：无。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.core.exception_handlers import setup_exception_handlers
from backend.middleware.rate_limit import RateLimiter

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self, result: list[int]) -> None:
        self.result = result
        self.calls: list[tuple[Any, ...]] = []

    async def eval(self, *args: Any) -> list[int]:
        self.calls.append(args)
        return self.result


async def _limited_client(
    fake_redis: FakeRedis,
    *,
    trusted_proxy_cidrs: str | None = None,
) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    setup_exception_handlers(app)
    limiter = RateLimiter(times=2, seconds=60, trusted_proxy_cidrs=trusted_proxy_cidrs)

    @app.get("/limited", dependencies=[Depends(limiter)])
    async def limited(request: Request) -> dict[str, object]:
        return {"rate_limit": request.state.rate_limit}

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_records_allowed_result_returns_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis([1, 1])

    async def init_redis() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr("backend.middleware.rate_limit.redis_client.init", init_redis)

    async for client in _limited_client(fake_redis):
        response = await client.get("/limited")

    assert response.status_code == 200
    assert response.json() == {
        "rate_limit": {
            "rate_limit.allowed": True,
            "rate_limit.current_count": 1,
        }
    }
    assert fake_redis.calls


async def test_rejects_when_window_is_full_returns_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis([0, 2])

    async def init_redis() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr("backend.middleware.rate_limit.redis_client.init", init_redis)

    async for client in _limited_client(fake_redis):
        response = await client.get("/limited")

    assert response.status_code == 429
    assert response.json()["error_code"] == "TOO_MANY_REQUESTS"
    assert response.json()["details"] == {
        "limit_count": 2,
        "current_count": 2,
    }


async def test_uses_compact_unique_members_does_not_deduplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis([1, 1])
    random_values = iter([b"abcd", b"efgh"])

    async def init_redis() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr("backend.middleware.rate_limit.redis_client.init", init_redis)
    monkeypatch.setattr("backend.middleware.rate_limit.time.time", lambda: 123.456)
    monkeypatch.setattr(
        "backend.middleware.rate_limit.os.urandom",
        lambda size: next(random_values),
    )

    async for client in _limited_client(fake_redis):
        assert (await client.get("/limited")).status_code == 200
        assert (await client.get("/limited")).status_code == 200

    members = [call[6] for call in fake_redis.calls]
    assert members == ["123456:61626364", "123456:65666768"]
    assert all(len(member) == 15 for member in members)


async def test_trusted_proxy_uses_x_real_ip_for_rate_limit_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis([1, 1])

    async def init_redis() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr("backend.middleware.rate_limit.redis_client.init", init_redis)

    async for client in _limited_client(fake_redis, trusted_proxy_cidrs="127.0.0.1/32"):
        response = await client.get("/limited", headers={"x-real-ip": "203.0.113.10"})

    assert response.status_code == 200
    assert fake_redis.calls[0][2] == "rate_limit_sliding:203.0.113.10:/limited"


async def test_untrusted_peer_ignores_x_real_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis([1, 1])

    async def init_redis() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr("backend.middleware.rate_limit.redis_client.init", init_redis)

    async for client in _limited_client(fake_redis, trusted_proxy_cidrs="10.0.0.0/8"):
        response = await client.get("/limited", headers={"x-real-ip": "203.0.113.10"})

    assert response.status_code == 200
    assert fake_redis.calls[0][2] == "rate_limit_sliding:127.0.0.1:/limited"


async def test_trusted_proxy_ignores_invalid_x_real_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis([1, 1])

    async def init_redis() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr("backend.middleware.rate_limit.redis_client.init", init_redis)

    async for client in _limited_client(fake_redis, trusted_proxy_cidrs="127.0.0.1/32"):
        response = await client.get("/limited", headers={"x-real-ip": "not-an-ip"})

    assert response.status_code == 200
    assert fake_redis.calls[0][2] == "rate_limit_sliding:127.0.0.1:/limited"
