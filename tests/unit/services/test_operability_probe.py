"""T1-Lite operability probe service tests.

职责：验证 durable oldest-age 选择与 Redis eviction/restart delta 计算。
边界：使用 fake UoW / Redis，不连接真实基础设施。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.services.operability_probe import (
    OperabilityProbeService,
    observe_redis_role,
)


class FakeReadContext:
    def __init__(self, uow: object) -> None:
        self._uow = uow

    async def __aenter__(self) -> object:
        return self._uow

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeRedis:
    def __init__(
        self,
        *,
        run_id: str = "run-current",
        uptime: int = 900,
        evicted: int = 0,
        state: dict[object, object] | None = None,
    ) -> None:
        self.run_id = run_id
        self.uptime = uptime
        self.evicted = evicted
        self.state = state or {}
        self.saved: dict[str, object] = {}
        self.ttl: int | None = None

    async def info(self, section: str) -> dict[str, object]:
        if section == "server":
            return {"run_id": self.run_id, "uptime_in_seconds": self.uptime}
        return {"evicted_keys": self.evicted}

    async def hgetall(self, _name: str) -> dict[object, object]:
        return self.state

    async def hset(self, _name: str, *, mapping: dict[str, object]) -> int:
        self.saved = mapping
        return len(mapping)

    async def expire(self, _name: str, time: int) -> bool:
        self.ttl = time
        return True


async def test_observe_durable_backlog_selects_oldest_postgres_fact() -> None:
    now = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    uow = SimpleNamespace(
        chat_repo=SimpleNamespace(
            get_oldest_due_generation_recovery_at=AsyncMock(
                return_value=now - timedelta(seconds=90)
            )
        ),
        task_repo=SimpleNamespace(
            get_oldest_actionable_kb_task_at=AsyncMock(
                return_value=now - timedelta(seconds=180)
            )
        ),
        task_outbox_repo=SimpleNamespace(
            get_oldest_due_at=AsyncMock(return_value=now - timedelta(seconds=60))
        ),
    )
    uow.read_context = lambda: FakeReadContext(uow)

    observation = await OperabilityProbeService(
        uow  # type: ignore[arg-type]
    ).observe_durable_backlog(observed_at=now)

    assert observation.oldest_pending_source == "knowledge_task"
    assert observation.oldest_pending_age_seconds == 180
    assert observation.chat_due_age_seconds == 90
    assert observation.knowledge_outbox_due_age_seconds == 60


async def test_observe_redis_role_reports_restart_and_eviction_delta() -> None:
    current = FakeRedis(run_id="run-new", uptime=50, evicted=9)
    state = FakeRedis(state={b"run_id": b"run-old", b"evicted_keys": b"4"})

    observation = await observe_redis_role(
        role="taskiq",
        current_client=current,
        state_client=state,
    )

    assert observation.restart_detected is True
    assert observation.evicted_keys_delta == 5
    assert observation.evicted_keys_total == 9
    assert state.saved == {"run_id": "run-new", "evicted_keys": 9}
    assert state.ttl == 172_800


async def test_first_steady_redis_observation_does_not_alert() -> None:
    current = FakeRedis(run_id="run-current", uptime=900, evicted=7)
    state = FakeRedis()

    observation = await observe_redis_role(
        role="app",
        current_client=current,
        state_client=state,
    )

    assert observation.restart_detected is False
    assert observation.evicted_keys_delta == 0
