"""
core/concurrency.py — 全局并发控制

设计原则：
1. Semaphore 使用 threading.Lock 双重检查保护初始化，防止多协程同时触发
   懒初始化产生竞态（R2 修复）。
2. ChatWorkflow 与 ChatNonStreamWorkflow 共享同一 Semaphore 实例，
   确保 LLM / DB 并发上限是全局有效的（R4 修复）。
3. Semaphore 在首次访问时才创建（不在模块导入时），避免测试环境
   因没有 running event loop 而报错。
"""

import asyncio
import threading

from backend.core.config import settings

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
