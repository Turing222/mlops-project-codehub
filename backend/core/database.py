import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry import trace
from sqlalchemy import event, text
from sqlalchemy.engine import ExceptionContext
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from backend.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
_DB_TRACER = trace.get_tracer(__name__)
_INSTRUMENTED_ENGINE_IDS: set[int] = set()


def _env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY_ENV_VALUES


def _sql_operation_name(statement: str) -> str:
    if not statement:
        return "SQL"
    return statement.lstrip().split(None, 1)[0].upper()


def _instrument_engine(engine: AsyncEngine) -> None:
    if not _env_flag("ENABLE_OTEL_TRACES", "false"):
        return

    sync_engine = engine.sync_engine
    sync_engine_id = id(sync_engine)
    if sync_engine_id in _INSTRUMENTED_ENGINE_IDS:
        return
    _INSTRUMENTED_ENGINE_IDS.add(sync_engine_id)

    db_system = sync_engine.dialect.name
    db_name = engine.url.database or ""
    db_host = engine.url.host or ""
    db_port = engine.url.port

    @event.listens_for(sync_engine, "before_cursor_execute")
    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ) -> None:
        operation = _sql_operation_name(statement)
        span = _DB_TRACER.start_span(
            name=f"db.{operation.lower()}",
            kind=trace.SpanKind.CLIENT,
        )
        span.set_attribute("db.system", db_system)
        span.set_attribute("db.operation", operation)
        if db_name:
            span.set_attribute("db.name", db_name)
        if db_host:
            span.set_attribute("server.address", db_host)
        if db_port is not None:
            span.set_attribute("server.port", db_port)
        if statement:
            span.set_attribute("db.statement", statement.strip())
        context._otel_db_span = span

    @event.listens_for(sync_engine, "after_cursor_execute")
    def after_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ) -> None:
        span = getattr(context, "_otel_db_span", None)
        if span is None:
            return
        span.end()
        delattr(context, "_otel_db_span")

    @event.listens_for(sync_engine, "handle_error")
    def handle_error(exception_context: ExceptionContext) -> None:
        context = exception_context.execution_context
        if context is None:
            return

        span = getattr(context, "_otel_db_span", None)
        if span is None:
            return

        span.record_exception(exception_context.original_exception)
        span.set_status(trace.Status(trace.StatusCode.ERROR))
        span.end()
        delattr(context, "_otel_db_span")

    logger.info("OpenTelemetry 数据库 tracing 已启用: %s", settings.database_url_safe)


# 1. 配置化 Engine 创建函数 (不再直接在顶层实例化)
def create_db_assets() -> tuple[AsyncEngine, async_sessionmaker]:
    """工厂函数：创建 engine 和 session_maker"""
    engine = create_async_engine(
        settings.database_url,
        echo=settings.POSTGRES_DB_ECHO,  # 建议从配置中读取，不要硬编码 True
        pool_size=settings.POSTGRES_POOL_SIZE,
        max_overflow=settings.POSTGRES_MAX_OVERFLOW,
        pool_pre_ping=True,
    )
    _instrument_engine(engine)

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

    logger.info(
        "Database connection pool initialized. URL: %s",
        settings.database_url_safe,
    )

    try:
        # 在这里可以添加启动时的连接检查（防止配置错误导致启动后报错）
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        yield  # 运行权交还给 FastAPI，直到应用关闭

    finally:
        # 优雅停机：释放连接池
        await engine.dispose()
        logger.info("Database connection pool closed.")
