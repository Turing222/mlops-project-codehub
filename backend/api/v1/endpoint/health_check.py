import logging
import time

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# 建议：通过 app.state 共享 engine，避免每次都走 dependency injection 的完整生命周期
# 或者定义一个更轻量级的 get_engine 依赖

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/db_ready")
async def readiness_check(request: Request):
    """
    就绪检查：DBA 级的精细化监控
    """
    # 假设你在 app 初始化时将 engine 存入了 request.app.state
    engine: AsyncEngine = request.app.state.db_engine

    start_time = time.perf_counter()
    try:
        # 优化：使用 context manager 直接获取连接，绕过 Session 的各种状态管理
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        latency = time.perf_counter() - start_time

        # 针对 DBA 经验：建议此处监控连接池状态
        # SQLAlchemy 允许查看 Pool 统计
        pool_status = engine.pool.status()  # 仅限部分 Pool 实现，如 QueuePool

        if latency > 0.5:
            logger.warning(f"DB Slow: {latency:.3f}s | Pool: {pool_status}")

        return {
            "status": "ready",
            "latency": f"{latency:.4f}s",
            "pool": pool_status,  # 生产环境建议脱敏
        }
    except Exception as e:
        logger.critical(f"Database readiness failed: {e}", exc_info=True)
        # RFC 7807 标准：返回 503 Service Unavailable
        raise HTTPException(status_code=503, detail="Database connection failed") from e


@router.get("/live")
async def liveness_check():
    """
    存活检查：仅确保 FastAPI 进程本身在线
    """
    return {"status": "alive"}
