"""TaskIQ scheduler entrypoint.

职责：构建常驻 TaskIQ scheduler，并校验按 label 注册的定时任务。
边界：scheduler 只负责入队，任务执行仍由 worker 进程完成。
副作用：健康检查会导入配置的任务模块并读取 broker 上的 schedule 标签。
"""

from __future__ import annotations

import asyncio
import importlib
import os
from typing import TYPE_CHECKING

from taskiq.schedule_sources.label_based import LabelScheduleSource
from taskiq.scheduler.scheduler import TaskiqScheduler

from backend.infra.task_broker import broker

DEFAULT_SCHEDULER_MODULES = (
    "backend.worker.tasks.credit_tasks backend.worker.tasks.knowledge_tasks "
    "backend.worker.tasks.chat_recovery_tasks"
)
REQUIRED_SCHEDULE_KEYS = frozenset(
    {
        ("expire_credits", "expire_credits_daily"),
        (
            "recover_stale_knowledge_ingestions",
            "recover_stale_knowledge_ingestions_every_15m",
        ),
        (
            "reconcile_chat_generations",
            "reconcile_chat_generations_every_minute",
        ),
    }
)

if TYPE_CHECKING:  # pragma: no cover
    from taskiq.abc.schedule_source import ScheduleSource


def build_scheduler() -> TaskiqScheduler:
    """Factory invoked by ``taskiq scheduler <callable>``.

    Single :class:`LabelScheduleSource` bound to the application broker.
    Any task decorated with ``@broker.task(..., schedule=[...])`` is picked
    up automatically once taskiq imports its module.
    """
    sources: list[ScheduleSource] = [LabelScheduleSource(broker=broker)]
    return TaskiqScheduler(broker=broker, sources=sources)


def validate_scheduler_schedules() -> None:
    """Validate that required label schedules are discoverable."""
    modules = os.getenv(
        "TASKIQ_SCHEDULER_MODULES",
        DEFAULT_SCHEDULER_MODULES,
    ).split()
    for module_name in modules:
        importlib.import_module(module_name)

    async def collect_schedule_keys() -> set[tuple[str, str]]:
        scheduler = build_scheduler()
        schedule_keys: set[tuple[str, str]] = set()
        for source in scheduler.sources:
            await source.startup()
            for task in await source.get_schedules():
                schedule_keys.add((task.task_name, task.schedule_id))
        return schedule_keys

    schedule_keys = asyncio.run(collect_schedule_keys())
    missing_keys = REQUIRED_SCHEDULE_KEYS - schedule_keys
    if missing_keys:
        missing = ", ".join(
            f"task_name={task_name} schedule_id={schedule_id}"
            for task_name, schedule_id in sorted(missing_keys)
        )
        raise RuntimeError(f"Required scheduler tasks are not registered: {missing}")
