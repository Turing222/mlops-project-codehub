"""
ChatWorkflow 与 ChatNonStreamWorkflow 在同一 Python 进程内共享同一
Semaphore 实例，确保进程内的 LLM / DB 并发上限一致。

注意：asyncio.Semaphore 不是分布式并发控制；多 uvicorn worker、
多 TaskIQ worker、多容器部署时，每个进程都会拥有独立的 Semaphore。
"""

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from backend.core.config import settings
from backend.core.trace_utils import set_span_attributes, trace_span

# --- 线程锁：保护 Semaphore 的懒初始化 ---
_llm_lock = threading.Lock()
_db_lock = threading.Lock()

_llm_semaphore: asyncio.Semaphore | None = None
_db_semaphore: asyncio.Semaphore | None = None


def get_llm_semaphore() -> asyncio.Semaphore:
    """
    获取全局 LLM 并发 Semaphore（懒初始化 + 双重检查）。

    threading.Lock 保护初始化过程，asyncio.Semaphore 在已有 event loop
    的情况下被创建，两个 Workflow 共享同一实例。
    """
    global _llm_semaphore
    if _llm_semaphore is None:
        with _llm_lock:
            if _llm_semaphore is None:
                _llm_semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)
    return _llm_semaphore


def get_db_semaphore() -> asyncio.Semaphore:
    """
    获取全局 DB 并发 Semaphore（懒初始化 + 双重检查）。
    """
    global _db_semaphore
    if _db_semaphore is None:
        with _db_lock:
            if _db_semaphore is None:
                _db_semaphore = asyncio.Semaphore(settings.DB_MAX_CONCURRENCY)
    return _db_semaphore


@asynccontextmanager
async def traced_semaphore_slot(
    name: str,
    semaphore: asyncio.Semaphore,
    limit: int,
    attributes: Mapping[str, Any] | None = None,
) -> AsyncIterator[None]:
    """
    Acquire a semaphore slot and expose queue/hold timing as a child trace span.
    """
    span_attrs: dict[str, Any] = {
        "concurrency.name": name,
        "concurrency.limit": limit,
    }
    if attributes:
        span_attrs.update(attributes)

    with trace_span(f"concurrency.{name}", span_attrs) as span:
        start = time.perf_counter()
        await semaphore.acquire()
        acquired_at = time.perf_counter()
        set_span_attributes(
            span,
            {
                "concurrency.wait_ms": (acquired_at - start) * 1000,
                "concurrency.acquired": True,
            },
        )
        try:
            yield
        finally:
            hold_ms = (time.perf_counter() - acquired_at) * 1000
            set_span_attributes(span, {"concurrency.hold_ms": hold_ms})
            semaphore.release()


def llm_concurrency_slot(
    attributes: Mapping[str, Any] | None = None,
) -> AbstractAsyncContextManager[None]:
    return traced_semaphore_slot(
        "llm",
        get_llm_semaphore(),
        settings.LLM_MAX_CONCURRENCY,
        attributes,
    )


def db_concurrency_slot(
    attributes: Mapping[str, Any] | None = None,
) -> AbstractAsyncContextManager[None]:
    return traced_semaphore_slot(
        "db",
        get_db_semaphore(),
        settings.DB_MAX_CONCURRENCY,
        attributes,
    )


def reset_semaphores() -> None:
    """
    测试专用：重置 Semaphore 实例，以便在不同 event loop 中重新初始化。
    生产代码不应调用此函数。
    """
    global _llm_semaphore, _db_semaphore
    with _llm_lock:
        _llm_semaphore = None
    with _db_lock:
        _db_semaphore = None
