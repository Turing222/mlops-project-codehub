"""T1-Lite scheduled operability task tests.

职责：验证 heartbeat 汇总 queue/backlog/Redis fields，并产生 eviction/restart stable events。
边界：调用 TaskIQ original function，所有 DB/Redis 依赖均为 fake。
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from backend.services.operability_probe import (
    DurableBacklogObservation,
    RedisRoleObservation,
)
from backend.worker.tasks import operability_tasks


async def test_heartbeat_emits_bounded_end_to_end_fields(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app_redis = object()
    taskiq_redis = AsyncMock()
    taskiq_redis.llen.return_value = 7
    backlog = DurableBacklogObservation(
        oldest_pending_age_seconds=240,
        oldest_pending_source="knowledge_task",
        chat_due_age_seconds=30,
        knowledge_task_age_seconds=240,
        knowledge_outbox_due_age_seconds=60,
    )
    fake_service = AsyncMock()
    fake_service.observe_durable_backlog.return_value = backlog
    monkeypatch.setattr(
        operability_tasks.redis_client, "init", AsyncMock(return_value=app_redis)
    )
    monkeypatch.setattr(
        operability_tasks.redis_client,
        "get_taskiq_client",
        AsyncMock(return_value=taskiq_redis),
    )
    monkeypatch.setattr(
        operability_tasks,
        "OperabilityProbeService",
        lambda _uow: fake_service,
    )
    monkeypatch.setattr(
        operability_tasks, "SQLAlchemyUnitOfWork", lambda _factory: object()
    )
    monkeypatch.setattr(
        operability_tasks, "get_worker_session_factory", lambda: object()
    )
    monkeypatch.setattr(
        operability_tasks,
        "observe_redis_role",
        AsyncMock(
            side_effect=[
                RedisRoleObservation("app", 900, 3, 2, False),
                RedisRoleObservation("taskiq", 30, 0, 0, True),
            ]
        ),
    )
    caplog.set_level(logging.INFO, logger=operability_tasks.__name__)

    result = (
        await operability_tasks.emit_t1_lite_operability_heartbeat_task.original_func()
    )

    assert result["event"] == "t1_lite_heartbeat_completed"
    assert result["queue_depth"] == 7
    assert result["oldest_pending_age_seconds"] == 240
    assert result["oldest_pending_source"] == "knowledge_task"
    assert result["redis_roles_observed"] == 2
    assert result["probe_status"] == "ok"
    events = {getattr(record, "event", None) for record in caplog.records}
    assert "redis_eviction_detected" in events
    assert "redis_restart_detected" in events
    assert "t1_lite_heartbeat_completed" in events
    risk_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None)
        in {"redis_eviction_detected", "redis_restart_detected"}
    ]
    assert all(isinstance(record.duration_ms, float) for record in risk_records)
