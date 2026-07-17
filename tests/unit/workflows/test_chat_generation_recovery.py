"""Chat generation recovery workflow tests.

职责：验证 PREPARED/QUEUED/RUNNING 的有界恢复、CAS 冲突和失败收敛。
边界：使用 fake UoW/dispatcher，不连接 PostgreSQL、Redis 或 TaskIQ；副作用：无。
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.application.chat.generation_recovery import (
    CONTEXT_UNAVAILABLE_CODE,
    DISPATCH_EXHAUSTED_CODE,
    LEASE_EXPIRED_CODE,
    ChatGenerationRecoveryService,
)
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.models.enums import (
    ChatGenerationDispatchMode,
    ChatGenerationStatus,
    MessageStatus,
)
from backend.models.schemas.chat.payloads import (
    GenerationDispatchContext,
    GenerationPayload,
)


class FakeRecoveryUow:
    def __init__(self) -> None:
        self.chat_repo = AsyncMock()
        self.chat_repo.update_message_status.return_value = MagicMock()

    async def __aenter__(self) -> FakeRecoveryUow:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    @asynccontextmanager
    async def read_context(self):
        yield self


def _dispatch_context() -> dict[str, object]:
    return GenerationDispatchContext(
        mode=ChatGenerationDispatchMode.STREAM,
        generation_payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="recover me",
        ),
        idempotency_lock_key="idempotency:recover",
    ).model_dump(mode="json")


def _request(
    status: ChatGenerationStatus,
    *,
    dispatch_attempts: int,
    task_id: str | None = None,
    lease_token: str | None = None,
    dispatch_context: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        client_request_id="client-recovery",
        assistant_message_id=uuid.uuid4(),
        status=status,
        attempt=1,
        dispatch_attempts=dispatch_attempts,
        task_id=task_id,
        lease_token=lease_token,
        dispatch_context=dispatch_context or _dispatch_context(),
        recovery_due_at=datetime.now(UTC) - timedelta(seconds=1),
        lease_expires_at=None,
    )


def _service(
    uow: FakeRecoveryUow,
    dispatcher: AsyncMock,
) -> ChatGenerationRecoveryService:
    return ChatGenerationRecoveryService(
        uow=cast(AbstractUnitOfWork, uow),
        dispatcher=dispatcher,
        recovery_seconds=300,
        max_dispatch_attempts=3,
        batch_size=25,
    )


async def test_due_prepared_request_is_queued_and_dispatched_once() -> None:
    now = datetime.now(UTC)
    request = _request(ChatGenerationStatus.PREPARED, dispatch_attempts=0)
    uow = FakeRecoveryUow()
    uow.chat_repo.get_due_generation_requests.return_value = [request]
    uow.chat_repo.try_queue_generation_request.return_value = True
    dispatcher = AsyncMock()

    result = await _service(uow, dispatcher).reconcile_due_requests(now=now)

    assert result.scanned_count == 1
    assert result.prepared_dispatched_count == 1
    queue_kwargs = uow.chat_repo.try_queue_generation_request.await_args.kwargs
    assert queue_kwargs["request_id"] == request.id
    assert queue_kwargs["expected_attempt"] == 1
    assert queue_kwargs["recovery_due_at"] == now + timedelta(seconds=300)
    dispatch_kwargs = dispatcher.enqueue_generation_recovery.await_args.kwargs
    assert dispatch_kwargs["generation_attempt"].task_id == queue_kwargs["task_id"]
    assert (
        dispatch_kwargs["generation_attempt"].lease_token == queue_kwargs["lease_token"]
    )


async def test_duplicate_prepared_scanner_loses_cas_without_dispatch() -> None:
    request = _request(ChatGenerationStatus.PREPARED, dispatch_attempts=0)
    uow = FakeRecoveryUow()
    uow.chat_repo.get_due_generation_requests.return_value = [request]
    uow.chat_repo.try_queue_generation_request.return_value = False
    dispatcher = AsyncMock()

    result = await _service(uow, dispatcher).reconcile_due_requests()

    assert result.conflict_count == 1
    dispatcher.enqueue_generation_recovery.assert_not_awaited()


async def test_due_queued_request_preserves_attempt_and_broker_identity() -> None:
    request = _request(
        ChatGenerationStatus.QUEUED,
        dispatch_attempts=1,
        task_id="stable-task",
        lease_token="stable-lease",
    )
    uow = FakeRecoveryUow()
    uow.chat_repo.get_due_generation_requests.return_value = [request]
    uow.chat_repo.try_reserve_generation_request_redispatch.return_value = 2
    dispatcher = AsyncMock()

    result = await _service(uow, dispatcher).reconcile_due_requests()

    assert result.queued_redispatched_count == 1
    reserve_kwargs = (
        uow.chat_repo.try_reserve_generation_request_redispatch.await_args.kwargs
    )
    assert reserve_kwargs["expected_dispatch_attempts"] == 1
    assert reserve_kwargs["max_dispatch_attempts"] == 3
    dispatch_attempt = dispatcher.enqueue_generation_recovery.await_args.kwargs[
        "generation_attempt"
    ]
    assert dispatch_attempt.attempt == request.attempt
    assert dispatch_attempt.task_id == "stable-task"
    assert dispatch_attempt.lease_token == "stable-lease"


async def test_exhausted_queue_fails_request_and_assistant_atomically(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = _request(
        ChatGenerationStatus.QUEUED,
        dispatch_attempts=3,
        task_id="exhausted-task",
        lease_token="exhausted-lease",
    )
    uow = FakeRecoveryUow()
    uow.chat_repo.get_due_generation_requests.return_value = [request]
    uow.chat_repo.try_fail_due_generation_request.return_value = True
    dispatcher = AsyncMock()
    caplog.set_level(
        logging.WARNING,
        logger="backend.application.chat.generation_recovery",
    )

    result = await _service(uow, dispatcher).reconcile_due_requests()

    assert result.failed_count == 1
    fail_kwargs = uow.chat_repo.try_fail_due_generation_request.await_args.kwargs
    assert fail_kwargs["error_code"] == DISPATCH_EXHAUSTED_CODE
    message_kwargs = uow.chat_repo.update_message_status.await_args.kwargs
    assert message_kwargs["message_id"] == request.assistant_message_id
    assert message_kwargs["status"] == MessageStatus.FAILED
    dispatcher.enqueue_generation_recovery.assert_not_awaited()
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "chat_generation_recovery_failed"
    )
    fields = record.__dict__
    assert fields["error_code"] == DISPATCH_EXHAUSTED_CODE
    assert fields["generation_request_id"] == str(request.id)
    assert fields["attempt"] == request.attempt
    assert fields["status"] == str(ChatGenerationStatus.FAILED)
    assert fields["previous_status"] == str(request.status)
    assert fields["task_id"] == request.task_id
    assert fields["dispatch_attempts"] == request.dispatch_attempts
    assert fields["previous_dispatch_attempts"] == request.dispatch_attempts
    assert fields["recovery_due_at"] == request.recovery_due_at


async def test_expired_running_request_fails_without_automatic_replay() -> None:
    request = _request(
        ChatGenerationStatus.RUNNING,
        dispatch_attempts=1,
        task_id="running-task",
        lease_token="running-lease",
    )
    uow = FakeRecoveryUow()
    uow.chat_repo.get_due_generation_requests.return_value = [request]
    uow.chat_repo.try_fail_due_generation_request.return_value = True
    dispatcher = AsyncMock()

    result = await _service(uow, dispatcher).reconcile_due_requests()

    assert result.failed_count == 1
    fail_kwargs = uow.chat_repo.try_fail_due_generation_request.await_args.kwargs
    assert fail_kwargs["expected_status"] == ChatGenerationStatus.RUNNING
    assert fail_kwargs["error_code"] == LEASE_EXPIRED_CODE
    dispatcher.enqueue_generation_recovery.assert_not_awaited()


async def test_invalid_dispatch_context_becomes_explicit_retryable_failure() -> None:
    request = _request(
        ChatGenerationStatus.PREPARED,
        dispatch_attempts=0,
        dispatch_context={"schema_version": 999},
    )
    uow = FakeRecoveryUow()
    uow.chat_repo.get_due_generation_requests.return_value = [request]
    uow.chat_repo.try_fail_due_generation_request.return_value = True
    dispatcher = AsyncMock()

    result = await _service(uow, dispatcher).reconcile_due_requests()

    assert result.failed_count == 1
    fail_kwargs = uow.chat_repo.try_fail_due_generation_request.await_args.kwargs
    assert fail_kwargs["error_code"] == CONTEXT_UNAVAILABLE_CODE
    dispatcher.enqueue_generation_recovery.assert_not_awaited()


async def test_broker_error_leaves_reserved_request_for_next_due_scan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = _request(
        ChatGenerationStatus.QUEUED,
        dispatch_attempts=1,
        task_id="retry-task",
        lease_token="retry-lease",
    )
    uow = FakeRecoveryUow()
    uow.chat_repo.get_due_generation_requests.return_value = [request]
    uow.chat_repo.try_reserve_generation_request_redispatch.return_value = 2
    dispatcher = AsyncMock()
    dispatcher.enqueue_generation_recovery.side_effect = ConnectionError(
        "broker unavailable"
    )
    caplog.set_level(
        logging.ERROR,
        logger="backend.application.chat.generation_recovery",
    )

    result = await _service(uow, dispatcher).reconcile_due_requests()

    assert result.dispatch_error_count == 1
    assert result.failed_count == 0
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "chat_generation_recovery_dispatch_failed"
    )
    fields = record.__dict__
    assert fields["generation_request_id"] == str(request.id)
    assert fields["client_request_id"] == request.client_request_id
    assert fields["attempt"] == request.attempt
    assert fields["status"] == str(ChatGenerationStatus.QUEUED)
    assert fields["previous_status"] == str(request.status)
    assert fields["task_id"] == request.task_id
    assert fields["dispatch_attempts"] == request.dispatch_attempts + 1
    assert fields["previous_dispatch_attempts"] == request.dispatch_attempts
    assert fields["recovery_due_at"] == request.recovery_due_at
