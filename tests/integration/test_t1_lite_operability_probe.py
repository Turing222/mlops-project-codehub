"""Real PostgreSQL and Redis contracts for the T1-Lite operability probe.

职责：验证 migrated DB 的 read-only oldest-age 查询、TaskIQ LLEN 与双 Redis INFO/state sampling。
边界：不创建业务数据、不派发任务；唯一 Redis observation keys 在测试结束时删除。
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

import pytest
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config.settings import settings
from backend.infra.task_broker import broker
from backend.infra.task_dispatcher import TASKIQ_QUEUE_NAME
from backend.services.operability_probe import (
    OperabilityProbeService,
    observe_redis_role,
)
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.worker.scheduler_entrypoint import build_scheduler
from backend.worker.tasks.operability_tasks import TASK_NAME
from tests.helpers.env import require_env

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_db,
    pytest.mark.requires_redis,
    pytest.mark.requires_taskiq,
]

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TASKIQ_BIN = BACKEND_ROOT / ".venv/bin/taskiq"
_WORKER_INHERIT_ENV_KEYS = (
    "APP_ENV",
    "BACKEND_LOG_LEVEL",
    "DATABASE_URL",
    "DEWFLOW_TEST_PROFILE",
    "PATH",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "POSTGRES_SERVER",
    "POSTGRES_SSL_MODE",
    "POSTGRES_USER",
    "REDIS_HOST",
    "REDIS_PASSWORD",
    "REDIS_PORT",
    "REDIS_URL",
    "SECRET_KEY",
    "TASKIQ_REDIS_HOST",
    "TASKIQ_REDIS_PORT",
    "TASKIQ_REDIS_URL",
    "TASKIQ_RESULT_TTL_SECONDS",
)


def _postgres_url() -> str:
    url = require_env("TEST_DATABASE_URL")
    if not url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url.split("?", 1)[0]


@pytest.fixture
def operability_worker(tmp_path: Path):
    """Run one real worker against the dedicated integration TaskIQ Redis."""
    if not TASKIQ_BIN.exists():
        pytest.skip(f"TaskIQ binary not found: {TASKIQ_BIN}")

    parsed = urlparse(settings.taskiq_redis_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except OSError as exc:
        pytest.skip(f"TaskIQ integration requires Redis at {host}:{port}: {exc}")

    worker_env = {
        key: value
        for key in _WORKER_INHERIT_ENV_KEYS
        if (value := os.environ.get(key)) is not None
    }
    worker_env.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-chars")
    worker_env["PYTHONUNBUFFERED"] = "1"
    log_path = tmp_path / "operability-worker.jsonl"
    log_file = log_path.open("w+", encoding="utf-8")
    proc = subprocess.Popen(
        [
            str(TASKIQ_BIN),
            "worker",
            "backend.infra.task_broker:broker",
            "backend.worker.tasks.operability_tasks",
            "--workers",
            "1",
        ],
        cwd=BACKEND_ROOT,
        env=worker_env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(2)
    if proc.poll() is not None:
        log_file.flush()
        log_file.seek(0)
        output = log_file.read()
        log_file.close()
        raise AssertionError(f"TaskIQ operability worker exited early.\n{output}")

    try:
        yield proc, log_path
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        log_file.close()


async def test_real_probe_reads_bounded_db_and_redis_facts() -> None:
    engine = create_async_engine(
        _postgres_url(),
        connect_args=settings.database_connect_args,
        pool_pre_ping=True,
    )
    app_redis = redis.from_url(require_env("TEST_REDIS_URL"), decode_responses=True)
    taskiq_redis = redis.from_url(
        require_env("TEST_TASKIQ_REDIS_URL"),
        decode_responses=True,
    )
    app_role = f"integration-app-{uuid.uuid4().hex}"
    taskiq_role = f"integration-taskiq-{uuid.uuid4().hex}"
    app_state_key = f"dewflow:observability:redis:{app_role}:previous"
    taskiq_state_key = f"dewflow:observability:redis:{taskiq_role}:previous"
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        backlog = await OperabilityProbeService(
            SQLAlchemyUnitOfWork(session_factory)
        ).observe_durable_backlog()
        queue_depth = int(await taskiq_redis.llen(TASKIQ_QUEUE_NAME))
        app_observation = await observe_redis_role(
            role=app_role,
            current_client=app_redis,
            state_client=taskiq_redis,
        )
        taskiq_observation = await observe_redis_role(
            role=taskiq_role,
            current_client=taskiq_redis,
            state_client=app_redis,
        )

        assert backlog.oldest_pending_age_seconds >= 0
        assert backlog.oldest_pending_source in {
            "none",
            "chat_generation",
            "knowledge_task",
            "knowledge_outbox",
        }
        assert queue_depth >= 0
        assert app_observation.role == app_role
        assert taskiq_observation.role == taskiq_role
        assert app_observation.uptime_seconds > 0
        assert taskiq_observation.uptime_seconds > 0
    finally:
        await taskiq_redis.delete(app_state_key)
        await app_redis.delete(taskiq_state_key)
        await app_redis.aclose()
        await taskiq_redis.aclose()
        await engine.dispose()


async def test_scheduler_redis_worker_log_heartbeat_end_to_end(
    operability_worker,
) -> None:
    """Use the real scheduler send path, Redis broker, worker, and JSON log."""
    worker_proc, worker_log_path = operability_worker
    app_redis = redis.from_url(require_env("TEST_REDIS_URL"), decode_responses=True)
    taskiq_redis = redis.from_url(
        require_env("TEST_TASKIQ_REDIS_URL"),
        decode_responses=True,
    )
    task_id = f"itest-t1-lite-heartbeat-{uuid.uuid4().hex}"
    app_state_key = "dewflow:observability:redis:app:previous"
    taskiq_state_key = "dewflow:observability:redis:taskiq:previous"
    scheduler = build_scheduler()
    source = scheduler.sources[0]
    try:
        await taskiq_redis.delete(app_state_key, task_id)
        await app_redis.delete(taskiq_state_key)
        await scheduler.startup()
        await source.startup()
        schedule = next(
            item
            for item in await source.get_schedules()
            if item.task_name == TASK_NAME
            and item.schedule_id == "t1_lite_operability_heartbeat_every_minute"
        )
        schedule.task_id = task_id

        await scheduler.on_ready(source, schedule)

        for _ in range(60):
            if worker_proc.poll() is not None:
                break
            if await broker.result_backend.is_result_ready(task_id):
                break
            await asyncio.sleep(0.2)
        assert worker_proc.poll() is None
        assert await broker.result_backend.is_result_ready(task_id)
        task_result = await broker.result_backend.get_result(task_id)
        assert task_result.is_err is False
        result_payload = cast(dict[str, object], task_result.return_value)
        assert result_payload["event"] == "t1_lite_heartbeat_completed"
        assert result_payload["redis_roles_observed"] == 2

        heartbeat_record: dict[str, object] | None = None
        for _ in range(30):
            for line in worker_log_path.read_text(encoding="utf-8").splitlines():
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if candidate.get("event") == "t1_lite_heartbeat_completed":
                    heartbeat_record = candidate
                    break
            if heartbeat_record is not None:
                break
            await asyncio.sleep(0.1)

        assert heartbeat_record is not None
        assert heartbeat_record["task_name"] == TASK_NAME
        assert isinstance(heartbeat_record["heartbeat_id"], str)
        assert heartbeat_record["probe_status"] == "ok"
        assert heartbeat_record["redis_roles_observed"] == 2
        assert isinstance(heartbeat_record["queue_depth"], int)
        assert isinstance(heartbeat_record["oldest_pending_age_seconds"], int)
    finally:
        await scheduler.shutdown()
        await taskiq_redis.delete(app_state_key, task_id)
        await app_redis.delete(taskiq_state_key)
        await app_redis.aclose()
        await taskiq_redis.aclose()
