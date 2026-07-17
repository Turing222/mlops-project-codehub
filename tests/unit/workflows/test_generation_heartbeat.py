"""Generation lease heartbeat unit tests.

职责：验证 immediate/periodic lease renewal、fence rejection 与停止行为。
边界：使用共享 AsyncMock repository，不连接真实 PostgreSQL；副作用：无。
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

from backend.application.chat.generation_heartbeat import GenerationLeaseHeartbeat
from backend.models.schemas.chat.payloads import GenerationAttemptPayload


class FakeHeartbeatUow:
    def __init__(self, chat_repo: AsyncMock) -> None:
        self.chat_repo = chat_repo

    async def __aenter__(self) -> FakeHeartbeatUow:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _attempt() -> GenerationAttemptPayload:
    return GenerationAttemptPayload(
        request_id=uuid.uuid4(),
        attempt=2,
        task_id="heartbeat-task",
        lease_token="heartbeat-lease",
    )


async def test_heartbeat_renews_immediately_and_periodically() -> None:
    chat_repo = AsyncMock()
    chat_repo.try_heartbeat_generation_request.return_value = True
    attempt = _attempt()
    heartbeat = GenerationLeaseHeartbeat(
        uow_factory=lambda: FakeHeartbeatUow(chat_repo),
        generation_attempt=attempt,
        interval_seconds=0.01,
        lease_seconds=120,
    )

    assert await heartbeat.start() is True
    await asyncio.sleep(0.035)
    await heartbeat.stop()

    assert chat_repo.try_heartbeat_generation_request.await_count >= 3
    first_call = chat_repo.try_heartbeat_generation_request.await_args_list[0].kwargs
    assert first_call["request_id"] == attempt.request_id
    assert first_call["expected_attempt"] == attempt.attempt
    assert first_call["lease_token"] == attempt.lease_token
    assert first_call["lease_expires_at"] > first_call["heartbeat_at"]


async def test_heartbeat_rejection_prevents_periodic_task_start() -> None:
    chat_repo = AsyncMock()
    chat_repo.try_heartbeat_generation_request.return_value = False
    heartbeat = GenerationLeaseHeartbeat(
        uow_factory=lambda: FakeHeartbeatUow(chat_repo),
        generation_attempt=_attempt(),
        interval_seconds=0.01,
    )

    assert await heartbeat.start() is False
    assert heartbeat.lease_lost is True
    await heartbeat.stop()
    chat_repo.try_heartbeat_generation_request.assert_awaited_once()


async def test_heartbeat_without_durable_attempt_is_noop() -> None:
    chat_repo = AsyncMock()
    heartbeat = GenerationLeaseHeartbeat(
        uow_factory=lambda: FakeHeartbeatUow(chat_repo),
        generation_attempt=None,
    )

    assert await heartbeat.start() is True
    await heartbeat.stop()
    chat_repo.try_heartbeat_generation_request.assert_not_awaited()
