from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
import redis.asyncio as redis

from backend.config.settings import settings
from tests.integration.taskiq_test_tasks import integration_echo_task

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TASKIQ_BIN = BACKEND_ROOT / ".venv/bin/taskiq"


def _taskiq_redis_endpoint() -> tuple[str, int]:
    parsed = urlparse(settings.taskiq_redis_url)
    return parsed.hostname or "127.0.0.1", parsed.port or 6379


@pytest.fixture
async def taskiq_redis():
    client = redis.from_url(settings.taskiq_redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"TaskIQ integration test requires a live Redis instance: {exc}")

    yield client
    await client.aclose()


@pytest.fixture
def taskiq_worker():
    if not TASKIQ_BIN.exists():
        pytest.skip(f"TaskIQ binary not found: {TASKIQ_BIN}")

    host, port = _taskiq_redis_endpoint()
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except OSError as exc:
        pytest.skip(f"TaskIQ integration test requires Redis at {host}:{port}: {exc}")

    env = os.environ.copy()
    env.setdefault("SECRET_KEY", "test-secret")

    proc = subprocess.Popen(
        [
            str(TASKIQ_BIN),
            "worker",
            "backend.infra.task_broker:broker",
            "tests.integration.taskiq_test_tasks",
            "--workers",
            "1",
        ],
        cwd=BACKEND_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    time.sleep(2)
    if proc.poll() is not None:
        output = ""
        if proc.stdout is not None:
            output = proc.stdout.read()
        raise AssertionError(f"TaskIQ worker exited early.\n{output}")

    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


@pytest.mark.asyncio
async def test_taskiq_worker_consumes_task_from_redis(taskiq_worker, taskiq_redis):
    result_key = f"itest:taskiq:{uuid.uuid4().hex}"
    expected_value = "hello-taskiq"

    await taskiq_redis.delete(result_key)

    try:
        await integration_echo_task.kiq(result_key, expected_value)

        actual_value = None
        for _ in range(50):
            actual_value = await taskiq_redis.get(result_key)
            if actual_value == expected_value:
                break
            await asyncio.sleep(0.2)

        assert actual_value == expected_value
    finally:
        await taskiq_redis.delete(result_key)
