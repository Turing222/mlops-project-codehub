"""Scheduler entrypoint unit tests.

职责：验证 TaskIQ scheduler 健康检查能发现必需的 label schedules。
边界：不启动 scheduler 常驻循环，不连接 Redis 或数据库。
副作用：导入 worker task 模块会向进程内 broker 注册任务。
"""

import pytest


def test_validate_scheduler_schedules_discovers_required_tasks(monkeypatch) -> None:
    from backend.worker import scheduler_entrypoint

    monkeypatch.setenv(
        "TASKIQ_SCHEDULER_MODULES",
        "backend.worker.tasks.credit_tasks backend.worker.tasks.knowledge_tasks "
        "backend.worker.tasks.chat_recovery_tasks "
        "backend.worker.tasks.operability_tasks",
    )

    scheduler_entrypoint.validate_scheduler_schedules()


def test_validate_scheduler_schedules_reports_missing_required_task(
    monkeypatch,
) -> None:
    from backend.worker import scheduler_entrypoint

    monkeypatch.setenv(
        "TASKIQ_SCHEDULER_MODULES",
        "backend.worker.tasks.credit_tasks backend.worker.tasks.knowledge_tasks "
        "backend.worker.tasks.chat_recovery_tasks",
    )
    monkeypatch.setattr(
        scheduler_entrypoint,
        "REQUIRED_SCHEDULE_KEYS",
        frozenset({("missing_task", "missing_schedule")}),
    )

    with pytest.raises(RuntimeError, match="missing_schedule"):
        scheduler_entrypoint.validate_scheduler_schedules()


def test_scheduler_requires_chat_generation_recovery_schedule() -> None:
    from backend.worker import scheduler_entrypoint

    assert (
        "reconcile_chat_generations",
        "reconcile_chat_generations_every_minute",
    ) in scheduler_entrypoint.REQUIRED_SCHEDULE_KEYS
    assert (
        "backend.worker.tasks.chat_recovery_tasks"
        in scheduler_entrypoint.DEFAULT_SCHEDULER_MODULES
    )


def test_scheduler_requires_t1_lite_heartbeat_schedule() -> None:
    from backend.worker import scheduler_entrypoint

    assert (
        "emit_t1_lite_operability_heartbeat",
        "t1_lite_operability_heartbeat_every_minute",
    ) in scheduler_entrypoint.REQUIRED_SCHEDULE_KEYS
    assert (
        "backend.worker.tasks.operability_tasks"
        in scheduler_entrypoint.DEFAULT_SCHEDULER_MODULES
    )
