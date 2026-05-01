"""Process-local concurrency gates.

职责：为聊天 workflow 提供进程内共享的 LLM/DB semaphore 和 trace 计时。
边界：asyncio.Semaphore 不是分布式限流；多 worker/多容器各自拥有独立额度。
副作用：等待和持有时长会写入当前 trace span。
"""

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from backend.config.settings import settings
from backend.observability.trace_utils import set_span_attributes, trace_span

# 懒初始化可能跨线程触发，用线程锁保护同一进程内的单例。
_llm_lock = threading.Lock()
_db_lock = threading.Lock()

_llm_semaphore: asyncio.Semaphore | None = None
_db_semaphore: asyncio.Semaphore | None = None


def get_llm_semaphore() -> asyncio.Semaphore:
    """返回进程内共享的 LLM semaphore。"""
    global _llm_semaphore
    if _llm_semaphore is None:
        with _llm_lock:
            if _llm_semaphore is None:
                _llm_semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)
    return _llm_semaphore


def get_db_semaphore() -> asyncio.Semaphore:
    """返回进程内共享的 DB semaphore。"""
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
    """获取 semaphore 槽位，并记录排队和持有时长。"""
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
    """返回 LLM 并发槽位上下文。"""
    return traced_semaphore_slot(
        "llm",
        get_llm_semaphore(),
        settings.LLM_MAX_CONCURRENCY,
        attributes,
    )


def db_concurrency_slot(
    attributes: Mapping[str, Any] | None = None,
) -> AbstractAsyncContextManager[None]:
    """返回 DB 并发槽位上下文。"""
    return traced_semaphore_slot(
        "db",
        get_db_semaphore(),
        settings.DB_MAX_CONCURRENCY,
        attributes,
    )


def reset_semaphores() -> None:
    """测试专用：跨 event loop 用例结束后重置 semaphore 单例。"""
    global _llm_semaphore, _db_semaphore
    with _llm_lock:
        _llm_semaphore = None
    with _db_lock:
        _db_semaphore = None
