"""Task worker healthcheck.

职责：检查 TaskIQ worker 进程数量和队列 Redis 可用性。
边界：只用于容器/运维健康检查，不验证具体任务执行能力。
失败处理：异常会写入 stderr 并以非零退出码返回。
"""

from __future__ import annotations

import asyncio
import os
import sys

import redis.asyncio as redis

from backend.core.config import settings


def _count_taskiq_worker_processes() -> int:
    count = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue

        cmdline_path = f"/proc/{entry}/cmdline"
        try:
            with open(cmdline_path, "rb") as cmdline_file:
                raw = cmdline_file.read()
        except OSError:
            continue

        if not raw:
            continue

        cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
        if "taskiq worker" in cmdline:
            count += 1

    return count


async def _check_redis() -> None:
    client = redis.from_url(
        settings.taskiq_redis_url,
        decode_responses=True,
    )
    try:
        pong = await client.ping()
    finally:
        await client.aclose()

    if pong is not True:
        raise RuntimeError("Task worker healthcheck ping to Redis did not return True")


async def _main() -> int:
    min_processes = int(os.getenv("TASKIQ_HEALTH_MIN_PROCESSES", "2"))
    process_count = _count_taskiq_worker_processes()
    if process_count < min_processes:
        raise RuntimeError(
            "Task worker process count below threshold: "
            f"expected>={min_processes}, actual={process_count}"
        )

    await _check_redis()
    return 0


def main() -> int:
    """命令行入口，返回 shell 友好的退出码。"""
    try:
        return asyncio.run(_main())
    except Exception as exc:
        print(f"task_worker healthcheck failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
