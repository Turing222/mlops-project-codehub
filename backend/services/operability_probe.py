"""Bounded operability observations for T1-Lite alert producers.

职责：读取 PostgreSQL durable backlog facts，并计算 Redis eviction / restart observation。
边界：不决定 alarm threshold、不执行 replay，也不记录用户或任务 payload。
副作用：Redis observation 会把上一采样值以短 TTL 存入另一 Redis role。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.contracts.interfaces import AbstractUnitOfWork

REDIS_OBSERVATION_STATE_TTL_SECONDS = 172_800
REDIS_RECENT_RESTART_WINDOW_SECONDS = 180


@dataclass(frozen=True, slots=True)
class DurableBacklogObservation:
    oldest_pending_age_seconds: int
    oldest_pending_source: str
    chat_due_age_seconds: int
    knowledge_task_age_seconds: int
    knowledge_outbox_due_age_seconds: int


@dataclass(frozen=True, slots=True)
class RedisRoleObservation:
    role: str
    uptime_seconds: int
    evicted_keys_total: int
    evicted_keys_delta: int
    restart_detected: bool


class OperabilityProbeService:
    """Read bounded, non-mutating durable backlog measurements."""

    def __init__(self, uow: AbstractUnitOfWork) -> None:
        self._uow = uow

    async def observe_durable_backlog(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> DurableBacklogObservation:
        current_time = observed_at or datetime.now(UTC)
        async with self._uow.read_context():
            # Repositories in one UoW share one AsyncSession; SQLAlchemy forbids
            # concurrent operations on that session, so keep these bounded reads
            # sequential inside the same read-only context.
            chat_due_at = (
                await self._uow.chat_repo.get_oldest_due_generation_recovery_at(
                    due_at=current_time
                )
            )
            task_due_at = await self._uow.task_repo.get_oldest_actionable_kb_task_at(
                due_at=current_time
            )
            outbox_due_at = await self._uow.task_outbox_repo.get_oldest_due_at(
                due_at=current_time
            )

        candidates = {
            "chat_generation": chat_due_at,
            "knowledge_task": task_due_at,
            "knowledge_outbox": outbox_due_at,
        }
        present = {key: value for key, value in candidates.items() if value is not None}
        oldest_source = min(present, key=present.__getitem__) if present else "none"
        return DurableBacklogObservation(
            oldest_pending_age_seconds=(
                _age_seconds(present[oldest_source], current_time) if present else 0
            ),
            oldest_pending_source=oldest_source,
            chat_due_age_seconds=_age_seconds(chat_due_at, current_time),
            knowledge_task_age_seconds=_age_seconds(task_due_at, current_time),
            knowledge_outbox_due_age_seconds=_age_seconds(
                outbox_due_at,
                current_time,
            ),
        )


async def observe_redis_role(
    *,
    role: str,
    current_client: Any,
    state_client: Any,
) -> RedisRoleObservation:
    server_info, stats_info = await asyncio.gather(
        current_client.info("server"),
        current_client.info("stats"),
    )
    run_id = str(server_info.get("run_id") or "")
    uptime_seconds = int(server_info.get("uptime_in_seconds") or 0)
    evicted_keys_total = int(stats_info.get("evicted_keys") or 0)
    state_key = f"dewflow:observability:redis:{role}:previous"
    previous = _normalize_hash(await state_client.hgetall(state_key))
    previous_run_id = previous.get("run_id", "")
    previous_evicted = previous.get("evicted_keys")
    evicted_keys_delta = (
        max(evicted_keys_total - int(previous_evicted), 0)
        if previous_evicted is not None
        else 0
    )
    restart_detected = bool(previous_run_id and previous_run_id != run_id) or (
        0 < uptime_seconds <= REDIS_RECENT_RESTART_WINDOW_SECONDS
    )
    await state_client.hset(
        state_key,
        mapping={"run_id": run_id, "evicted_keys": evicted_keys_total},
    )
    await state_client.expire(state_key, REDIS_OBSERVATION_STATE_TTL_SECONDS)
    return RedisRoleObservation(
        role=role,
        uptime_seconds=uptime_seconds,
        evicted_keys_total=evicted_keys_total,
        evicted_keys_delta=evicted_keys_delta,
        restart_detected=restart_detected,
    )


def _age_seconds(value: datetime | None, current_time: datetime) -> int:
    if value is None:
        return 0
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return max(int((current_time - normalized).total_seconds()), 0)


def _normalize_hash(value: dict[Any, Any]) -> dict[str, str]:
    return {
        (key.decode() if isinstance(key, bytes) else str(key)): (
            item.decode() if isinstance(item, bytes) else str(item)
        )
        for key, item in value.items()
    }
