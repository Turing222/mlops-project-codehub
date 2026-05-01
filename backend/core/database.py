"""Database engine lifecycle.

职责：按 Settings 创建 async SQLAlchemy engine/session factory，并接入可选 DB tracing。
边界：本模块不定义 repository 或事务边界；事务由 UnitOfWork 管理。
副作用：init_db 会在 FastAPI lifespan 中预热连接并在关闭时释放连接池。
"""

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


def create_db_assets() -> tuple[AsyncEngine, async_sessionmaker]:
    """创建 engine 和 session factory，供 app 与 worker 复用。"""
    engine = create_async_engine(
        settings.database_url,
        echo=settings.POSTGRES_DB_ECHO,
        pool_size=settings.POSTGRES_POOL_SIZE,
        max_overflow=settings.POSTGRES_MAX_OVERFLOW,
        pool_pre_ping=True,
        connect_args=settings.database_connect_args,
    )
    _instrument_engine(engine)

    session_factory = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    return engine, session_factory


@asynccontextmanager
async def init_db(app: FastAPI) -> AsyncGenerator[None, None]:
    """在 FastAPI lifespan 中注册数据库资源并负责关闭。"""
    engine, session_factory = create_db_assets()

    app.state.db_engine = engine
    app.state.session_factory = session_factory

    logger.info(
        "Database connection pool initialized. URL: %s",
        settings.database_url_safe,
    )

    try:
        # 启动期预热能尽早暴露数据库 URL、认证或网络配置错误。
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        yield

    finally:
        await engine.dispose()
        logger.info("Database connection pool closed.")
