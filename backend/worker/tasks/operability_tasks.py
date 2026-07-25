"""Scheduled T1-Lite operability heartbeat task.

职责：由 Scheduler 经 TaskIQ Redis 派发，在 Worker 中采样 queue、durable backlog 与 Redis health。
边界：只观测并输出结构化日志，不修改业务状态、不执行 replay 或恢复。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict

from backend.infra.redis import redis_client
from backend.infra.task_broker import broker
from backend.infra.task_dispatcher import TASKIQ_QUEUE_NAME
from backend.services.operability_probe import (
    DurableBacklogObservation,
    OperabilityProbeService,
    RedisRoleObservation,
    observe_redis_role,
)
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.worker.dependencies import get_worker_session_factory

logger = logging.getLogger(__name__)
TASK_NAME = "emit_t1_lite_operability_heartbeat"


def _empty_backlog() -> DurableBacklogObservation:
    return DurableBacklogObservation(0, "none", 0, 0, 0)


def _log_redis_observation(
    observation: RedisRoleObservation,
    *,
    duration_ms: float,
) -> None:
    fields = {
        "task_name": TASK_NAME,
        "redis_role": observation.role,
        "redis_uptime_seconds": observation.uptime_seconds,
        "redis_evicted_keys_total": observation.evicted_keys_total,
        "redis_evicted_keys_delta": observation.evicted_keys_delta,
        "duration_ms": duration_ms,
    }
    logger.info(
        "Redis health observed",
        extra={"event": "redis_health_observed", **fields},
    )
    if observation.evicted_keys_delta > 0:
        logger.warning(
            "Redis eviction delta detected",
            extra={
                "event": "redis_eviction_detected",
                "error_code": "REDIS_EVICTION_DETECTED",
                **fields,
            },
        )
    if observation.restart_detected:
        logger.warning(
            "Redis restart detected",
            extra={
                "event": "redis_restart_detected",
                "error_code": "REDIS_RESTART_DETECTED",
                **fields,
            },
        )


@broker.task(
    task_name=TASK_NAME,
    schedule=[
        {
            "cron": "* * * * *",
            "schedule_id": "t1_lite_operability_heartbeat_every_minute",
        }
    ],
)
async def emit_t1_lite_operability_heartbeat_task() -> dict[str, object]:
    """Emit one bounded Scheduler -> Redis -> Worker -> log canary."""
    started = time.perf_counter()
    heartbeat_id = uuid.uuid4().hex
    probe_status = "ok"
    backlog = _empty_backlog()
    queue_depth = 0
    redis_roles_observed = 0
    app_redis = await redis_client.init()
    taskiq_redis = await redis_client.get_taskiq_client()

    db_probe_started = time.perf_counter()
    try:
        backlog = await OperabilityProbeService(
            SQLAlchemyUnitOfWork(get_worker_session_factory())
        ).observe_durable_backlog()
    except Exception as exc:
        probe_status = "degraded"
        logger.error(
            "Durable backlog probe failed",
            extra={
                "event": "operability_probe_failed",
                "error_code": "OPERABILITY_DB_PROBE_FAILED",
                "task_name": TASK_NAME,
                "probe_component": "postgresql",
                "error_type": type(exc).__name__,
                "duration_ms": round(
                    (time.perf_counter() - db_probe_started) * 1000,
                    3,
                ),
            },
        )

    queue_probe_started = time.perf_counter()
    try:
        queue_depth = int(
            await taskiq_redis.llen(TASKIQ_QUEUE_NAME)  # type: ignore[invalid-await]
        )
    except Exception as exc:
        probe_status = "degraded"
        logger.error(
            "TaskIQ queue depth probe failed",
            extra={
                "event": "redis_probe_failed",
                "error_code": "TASKIQ_QUEUE_PROBE_FAILED",
                "task_name": TASK_NAME,
                "probe_component": "taskiq_queue",
                "error_type": type(exc).__name__,
                "duration_ms": round(
                    (time.perf_counter() - queue_probe_started) * 1000,
                    3,
                ),
            },
        )

    for role, current_client, state_client in (
        ("app", app_redis, taskiq_redis),
        ("taskiq", taskiq_redis, app_redis),
    ):
        redis_probe_started = time.perf_counter()
        try:
            observation = await observe_redis_role(
                role=role,
                current_client=current_client,
                state_client=state_client,
            )
            redis_roles_observed += 1
            _log_redis_observation(
                observation,
                duration_ms=round(
                    (time.perf_counter() - redis_probe_started) * 1000,
                    3,
                ),
            )
        except Exception as exc:
            probe_status = "degraded"
            logger.error(
                "Redis health probe failed",
                extra={
                    "event": "redis_probe_failed",
                    "error_code": "REDIS_HEALTH_PROBE_FAILED",
                    "task_name": TASK_NAME,
                    "probe_component": role,
                    "redis_role": role,
                    "error_type": type(exc).__name__,
                    "duration_ms": round(
                        (time.perf_counter() - redis_probe_started) * 1000,
                        3,
                    ),
                },
            )

    result = {
        "event": "t1_lite_heartbeat_completed",
        "task_name": TASK_NAME,
        "heartbeat_id": heartbeat_id,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "probe_status": probe_status,
        "queue_depth": queue_depth,
        "redis_roles_observed": redis_roles_observed,
        **asdict(backlog),
    }
    logger.info("T1-Lite operability heartbeat completed", extra=result)
    return result
