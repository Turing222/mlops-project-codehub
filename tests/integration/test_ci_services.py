"""CI service connectivity tests.

职责：验证集成测试环境中的 PostgreSQL 和 Redis 可达，不执行迁移或业务数据写入。
边界：仅做基础设施连通性探测，真实业务 API 行为由其他集成测试覆盖。
"""

from __future__ import annotations

import os

import pytest
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.config.settings import settings

pytestmark = pytest.mark.integration


def _is_ci() -> bool:
    return os.getenv("CI", "").strip().lower() == "true"


@pytest.mark.asyncio
@pytest.mark.requires_db
async def test_ci_postgres_service_is_reachable() -> None:
    url = os.getenv("TEST_DATABASE_URL") or settings.database_url
    if not url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # Strip query params (like sslmode=) that asyncpg doesn't accept
    # as connect_args — SSL is configured via connect_args instead.
    if "?" in url:
        url = url.split("?", 1)[0]
    engine = create_async_engine(
        url,
        connect_args=settings.database_connect_args,
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    except Exception as exc:
        if _is_ci():
            raise
        pytest.skip(f"PostgreSQL service is not reachable: {exc}")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.requires_redis
async def test_ci_redis_service_is_reachable() -> None:
    url = settings.redis_url
    client = redis.from_url(url, decode_responses=True)
    try:
        assert await client.ping() is True
    except Exception as exc:
        if _is_ci():
            raise
        pytest.skip(f"Redis service is not reachable: {exc}")
    finally:
        await client.aclose()
