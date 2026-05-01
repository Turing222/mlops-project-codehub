import asyncio
import logging
import time

from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.core.exceptions import app_dependency_unavailable

# 建议：通过 app.state 共享 engine，避免每次都走 dependency injection 的完整生命周期
# 或者定义一个更轻量级的 get_engine 依赖

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/db_ready")
async def readiness_check(request: Request) -> dict[str, str | float]:
    """
    就绪检查：DBA 级的精细化监控
    """
    # 假设你在 app 初始化时将 engine 存入了 request.app.state
    engine: AsyncEngine | None = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise app_dependency_unavailable(
            "数据库引擎未初始化",
            code="DATABASE_ENGINE_NOT_INITIALIZED",
        )

    start_time = time.perf_counter()
    try:
        # 超时保护，避免在 DB 半故障时健康检查悬挂
        async def _ping_db() -> None:
            async with engine.connect() as db_connection:
                await db_connection.execute(text("SELECT 1"))

        await asyncio.wait_for(_ping_db(), timeout=2.0)

        latency_ms = (time.perf_counter() - start_time) * 1000

        # 连接池状态只保留在日志中，不对外暴露
        pool_status = "unknown"
        try:
            pool_status = engine.pool.status()  # 仅限部分 Pool 实现，如 QueuePool
        except Exception:
            logger.debug("无法获取连接池状态", exc_info=True)

        if latency_ms > 500:
            logger.warning("DB Slow: %.2fms | Pool: %s", latency_ms, pool_status)

        return {
            "status": "ready",
            "latency_ms": round(latency_ms, 2),
        }
    except TimeoutError as e:
        logger.critical("Database readiness timeout", exc_info=True)
        raise app_dependency_unavailable(
            "数据库就绪检查超时",
            code="DATABASE_READINESS_TIMEOUT",
        ) from e
    except Exception as e:
        logger.critical("Database readiness failed: %s", e, exc_info=True)
        # RFC 7807 标准：返回 503 Service Unavailable
        raise app_dependency_unavailable(
            "数据库连接失败",
            code="DATABASE_CONNECTION_FAILED",
        ) from e


@router.get("/live")
async def liveness_check() -> dict[str, str]:
    """
    存活检查：仅确保 FastAPI 进程本身在线
    """
    return {"status": "alive"}
