import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from backend.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# 1. 配置化 Engine 创建函数 (不再直接在顶层实例化)
def create_db_assets() -> tuple[AsyncEngine, async_sessionmaker]:
    """工厂函数：创建 engine 和 session_maker"""
    engine = create_async_engine(
        settings.database_url,
        echo=settings.POSTGRES_DB_ECHO,  # 建议从配置中读取，不要硬编码 True
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

    session_factory = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    return engine, session_factory


# 2. 核心：Lifespan 资源注册器
@asynccontextmanager
async def init_db(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    负责数据库资源的完整生命周期管理。
    DBA 注意：这是你注入数据库预热逻辑（Warm-up）的最佳位置。
    """
    engine, session_factory = create_db_assets()

    # 挂载到 app.state
    app.state.db_engine = engine
    app.state.session_factory = session_factory

    logger.info("Database connection pool initialized.")

    try:
        # 在这里可以添加启动时的连接检查（防止配置错误导致启动后报错）
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        yield  # 运行权交还给 FastAPI，直到应用关闭

    finally:
        # 优雅停机：释放连接池
        await engine.dispose()
        logger.info("Database connection pool closed.")
