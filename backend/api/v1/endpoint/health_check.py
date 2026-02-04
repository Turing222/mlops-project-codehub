import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_session

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health/db_ready")
async def readiness_check(db: AsyncSession = Depends(get_session)):
    """
    就绪检查：确保 DB 能连通，且连接池没爆
    """
    try:
        # 1. 极简查询测试连通性
        start_time = time.perf_counter()
        await db.execute(text("SELECT 1"))
        latency = time.perf_counter() - start_time

        # 2. 如果延迟过高，可以在日志里报警（DBA 视角的预警）
        if latency > 0.5:  # 500ms
            logger.warning(f"Database slow response: {latency:.3f}s")

        return {
            "status": "ready",
            "database": "connected",
            "latency": f"{latency:.4f}s",
        }
    except Exception as e:
        # 这里的异常捕获非常重要，用于触发 K8s 的重启或剔除策略
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Database unreachable") from e


@router.get("/health/live")
async def liveness_check():
    """
    存活检查：仅确保 FastAPI 进程本身在线
    """
    return {"status": "alive"}
