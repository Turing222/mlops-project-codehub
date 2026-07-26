"""Real PostgreSQL contracts for durable Chat generation requests.

职责：验证 actor-scoped 唯一性、attempt/lease CAS 和 Workspace/session 授权；
边界：在一次事务内创建隔离 schema，不运行应用迁移、不触碰现有业务数据。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.application.chat.generation_recovery import (
    ChatGenerationRecoveryService,
)
from backend.application.chat.worker_persistence_handler import (
    GenerationAttemptRejected,
    WorkerPersistenceHandler,
)
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.infra.redis import RedisClient
from backend.models.enums import ChatGenerationStatus, MessageStatus
from backend.models.orm.chat import ChatGenerationRequest, ChatMessage
from backend.models.schemas.chat.payloads import (
    GenerationAttemptPayload,
    GenerationDispatchContext,
    GenerationPayload,
)
from backend.repositories.chat_repo import ChatRepository
from tests.helpers.env import require_env

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]


def _postgres_url() -> str:
    url = require_env("TEST_DATABASE_URL")
    if not url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url.split("?", 1)[0]


def _is_ci() -> bool:
    return os.getenv("CI", "").strip().lower() == "true"


@pytest.fixture
async def pg_session() -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession bound to a transaction-local isolated schema."""
    engine = create_async_engine(
        _postgres_url(),
        connect_args=settings.database_connect_args,
        pool_pre_ping=True,
    )
    schema = f"ws3_{uuid.uuid4().hex}"
    try:
        try:
            connection = await engine.connect()
        except Exception as exc:
            if _is_ci():
                raise
            pytest.skip(f"PostgreSQL service is not reachable: {exc}")
        try:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(
                    text(f'SET LOCAL search_path TO "{schema}", public')
                )
                for ddl in (
                    "CREATE TABLE users (id UUID PRIMARY KEY)",
                    """
                    CREATE TABLE workspaces (
                        id UUID PRIMARY KEY,
                        deleted_at TIMESTAMPTZ NULL
                    )
                    """,
                    """
                    CREATE TABLE chat_sessions (
                        id UUID PRIMARY KEY,
                        user_id UUID NOT NULL,
                        workspace_id UUID NULL,
                        deleted_at TIMESTAMPTZ NULL
                    )
                    """,
                    """
                    CREATE TABLE user_workspace_roles (
                        id UUID PRIMARY KEY,
                        user_id UUID NOT NULL,
                        workspace_id UUID NOT NULL
                    )
                    """,
                ):
                    await connection.execute(text(ddl))
                await connection.run_sync(ChatMessage.__table__.create)
                await connection.run_sync(ChatGenerationRequest.__table__.create)

                session = AsyncSession(bind=connection, expire_on_commit=False)
                try:
                    yield session
                finally:
                    await session.close()
            finally:
                await transaction.rollback()
        finally:
            await connection.close()
    finally:
        await engine.dispose()


class SessionBoundUow:
    """Nested-transaction UoW for exercising atomic persistence on one session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.chat_repo = ChatRepository(session)
        self._transaction = None

    async def __aenter__(self) -> SessionBoundUow:
        self._transaction = await self._session.begin_nested()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        assert self._transaction is not None
        if exc_type is None:
            await self._transaction.commit()
        else:
            await self._transaction.rollback()
        self._transaction = None

    @asynccontextmanager
    async def savepoint(self) -> AsyncIterator[SessionBoundUow]:
        async with self._session.begin_nested():
            yield self

    @asynccontextmanager
    async def read_context(self) -> AsyncIterator[SessionBoundUow]:
        yield self


async def _seed_scope(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    user_message_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    add_membership: bool = True,
) -> None:
    await session.execute(
        text("INSERT INTO users (id) VALUES (:id) ON CONFLICT DO NOTHING"),
        {"id": user_id},
    )
    if workspace_id is not None:
        await session.execute(
            text(
                "INSERT INTO workspaces (id, deleted_at) "
                "VALUES (:id, NULL) ON CONFLICT DO NOTHING"
            ),
            {"id": workspace_id},
        )
        if add_membership:
            await session.execute(
                text(
                    "INSERT INTO user_workspace_roles (id, user_id, workspace_id) "
                    "VALUES (:id, :user_id, :workspace_id)"
                ),
                {
                    "id": uuid.uuid4(),
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                },
            )
    await session.execute(
        text(
            "INSERT INTO chat_sessions "
            "(id, user_id, workspace_id, deleted_at) "
            "VALUES (:id, :user_id, :workspace_id, NULL)"
        ),
        {
            "id": session_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
        },
    )
    await session.execute(
        text(
            "INSERT INTO chat_messages (id, session_id, role, content, status) "
            "VALUES (:user_message_id, :session_id, 'user', 'question', 'success'), "
            "(:assistant_message_id, :session_id, 'assistant', '', 'thinking')"
        ),
        {
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "session_id": session_id,
        },
    )


async def _create_queued_request(
    session: AsyncSession,
    *,
    client_request_id: str,
    recovery_due_at: datetime,
) -> tuple[
    ChatRepository,
    ChatGenerationRequest,
    uuid.UUID,
    uuid.UUID,
    GenerationAttemptPayload,
]:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    await _seed_scope(
        session,
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )
    repo = ChatRepository(session)
    request = await repo.create_generation_request(
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        client_request_id=client_request_id,
        dispatch_context=GenerationDispatchContext(
            mode="stream",
            generation_payload=GenerationPayload(
                session_id=session_id,
                query_text="question",
            ),
        ).model_dump(mode="json"),
        recovery_due_at=recovery_due_at - timedelta(minutes=1),
    )
    attempt = GenerationAttemptPayload(
        request_id=request.id,
        attempt=1,
        task_id=f"task-{client_request_id}",
        lease_token=f"lease-{client_request_id}",
    )
    assert await repo.try_queue_generation_request(
        request_id=request.id,
        user_id=user_id,
        expected_attempt=attempt.attempt,
        task_id=attempt.task_id,
        lease_token=attempt.lease_token,
        queued_at=recovery_due_at - timedelta(minutes=2),
        recovery_due_at=recovery_due_at,
    )
    return repo, request, user_id, assistant_message_id, attempt


async def _create_running_request(
    session: AsyncSession,
    *,
    client_request_id: str,
) -> tuple[ChatRepository, ChatGenerationRequest, uuid.UUID, GenerationAttemptPayload]:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    await _seed_scope(
        session,
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )
    repo = ChatRepository(session)
    request = await repo.create_generation_request(
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        client_request_id=client_request_id,
    )
    attempt = GenerationAttemptPayload(
        request_id=request.id,
        attempt=1,
        task_id=f"task-{client_request_id}",
        lease_token=f"lease-{client_request_id}",
    )
    now = datetime.now(UTC)
    assert await repo.try_queue_generation_request(
        request_id=request.id,
        user_id=user_id,
        expected_attempt=attempt.attempt,
        task_id=attempt.task_id,
        lease_token=attempt.lease_token,
        queued_at=now,
        recovery_due_at=now + timedelta(minutes=1),
    )
    assert await repo.try_claim_generation_request(
        request_id=request.id,
        user_id=user_id,
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        expected_attempt=attempt.attempt,
        task_id=attempt.task_id,
        lease_token=attempt.lease_token,
        started_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )
    return repo, request, assistant_message_id, attempt


async def test_actor_scoped_client_request_id_is_unique_in_postgres(
    pg_session: AsyncSession,
) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    repo = ChatRepository(pg_session)

    scopes: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]] = []
    for user_id in (user_a, user_b, user_a):
        scope = (user_id, uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        scopes.append(scope)
        await _seed_scope(
            pg_session,
            user_id=scope[0],
            session_id=scope[1],
            user_message_id=scope[2],
            assistant_message_id=scope[3],
        )

    first = await repo.create_generation_request(
        user_id=scopes[0][0],
        session_id=scopes[0][1],
        user_message_id=scopes[0][2],
        assistant_message_id=scopes[0][3],
        client_request_id="shared-client-id",
    )
    second = await repo.create_generation_request(
        user_id=scopes[1][0],
        session_id=scopes[1][1],
        user_message_id=scopes[1][2],
        assistant_message_id=scopes[1][3],
        client_request_id="shared-client-id",
    )

    assert first.id != second.id
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await repo.create_generation_request(
                user_id=scopes[2][0],
                session_id=scopes[2][1],
                user_message_id=scopes[2][2],
                assistant_message_id=scopes[2][3],
                client_request_id="shared-client-id",
            )


async def test_attempt_and_lease_cas_reject_stale_worker_in_postgres(
    pg_session: AsyncSession,
) -> None:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    await _seed_scope(
        pg_session,
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )
    repo = ChatRepository(pg_session)
    request = await repo.create_generation_request(
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        client_request_id="cas-request",
    )
    now = datetime.now(UTC)

    assert await repo.try_queue_generation_request(
        request_id=request.id,
        user_id=user_id,
        expected_attempt=1,
        task_id="task-1",
        lease_token="lease-1",
        queued_at=now,
        recovery_due_at=now + timedelta(minutes=1),
    )
    assert not await repo.try_queue_generation_request(
        request_id=request.id,
        user_id=user_id,
        expected_attempt=1,
        task_id="duplicate-task",
        lease_token="duplicate-lease",
        queued_at=now,
        recovery_due_at=now + timedelta(minutes=1),
    )
    assert not await repo.try_claim_generation_request(
        request_id=request.id,
        user_id=user_id,
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        expected_attempt=1,
        task_id="task-1",
        lease_token="wrong-lease",
        started_at=now,
        lease_expires_at=now + timedelta(minutes=2),
    )
    assert not await repo.try_claim_generation_request(
        request_id=request.id,
        user_id=user_id,
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        expected_attempt=1,
        task_id="wrong-task",
        lease_token="lease-1",
        started_at=now,
        lease_expires_at=now + timedelta(minutes=2),
    )
    assert await repo.try_claim_generation_request(
        request_id=request.id,
        user_id=user_id,
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        expected_attempt=1,
        task_id="task-1",
        lease_token="lease-1",
        started_at=now,
        lease_expires_at=now + timedelta(minutes=2),
    )
    assert not await repo.try_heartbeat_generation_request(
        request_id=request.id,
        expected_attempt=2,
        lease_token="lease-1",
        heartbeat_at=now + timedelta(seconds=10),
        lease_expires_at=now + timedelta(minutes=3),
    )
    assert await repo.try_heartbeat_generation_request(
        request_id=request.id,
        expected_attempt=1,
        lease_token="lease-1",
        heartbeat_at=now + timedelta(seconds=10),
        lease_expires_at=now + timedelta(minutes=3),
    )
    failed_message = await repo.update_message_status(
        message_id=assistant_message_id,
        status=MessageStatus.FAILED,
        content="provider timed out",
        tokens_input=12,
        tokens_output=3,
        search_context={"stale": True},
        message_metadata={"metrics": {"attempt": 1}},
    )
    assert failed_message is not None
    assert await repo.try_finalize_generation_request(
        request_id=request.id,
        expected_attempt=1,
        lease_token="lease-1",
        target_status=ChatGenerationStatus.FAILED,
        finished_at=now + timedelta(seconds=20),
        retryable=True,
        error_code="LLM_TIMEOUT",
        error_message="provider timed out",
    )

    assert (
        await repo.try_retry_generation_request(
            request_id=request.id,
            user_id=user_id,
            expected_attempt=1,
            dispatch_context={"schema_version": 1, "mode": "stream"},
            recovery_due_at=now + timedelta(minutes=4),
        )
        == 2
    )
    assert await repo.reset_assistant_message_for_retry(message_id=assistant_message_id)
    reset_message = await repo.get_message(assistant_message_id)
    assert reset_message is not None
    assert reset_message.status == MessageStatus.THINKING
    assert reset_message.content == ""
    assert reset_message.tokens_input == 0
    assert reset_message.tokens_output == 0
    assert reset_message.search_context is None
    assert reset_message.message_metadata == {}
    assert not await repo.try_finalize_generation_request(
        request_id=request.id,
        expected_attempt=1,
        lease_token="lease-1",
        target_status=ChatGenerationStatus.SUCCEEDED,
        finished_at=now + timedelta(seconds=30),
    )
    assert await repo.try_queue_generation_request(
        request_id=request.id,
        user_id=user_id,
        expected_attempt=2,
        task_id="task-2",
        lease_token="lease-2",
        queued_at=now + timedelta(seconds=30),
        recovery_due_at=now + timedelta(minutes=5),
    )
    assert await repo.try_claim_generation_request(
        request_id=request.id,
        user_id=user_id,
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        expected_attempt=2,
        task_id="task-2",
        lease_token="lease-2",
        started_at=now + timedelta(seconds=31),
        lease_expires_at=now + timedelta(minutes=6),
    )
    assert await repo.try_finalize_generation_request(
        request_id=request.id,
        expected_attempt=2,
        lease_token="lease-2",
        target_status=ChatGenerationStatus.SUCCEEDED,
        finished_at=now + timedelta(seconds=40),
    )

    request_id = request.id
    pg_session.expire_all()
    final = await repo.get_generation_request_for_actor(
        request_id=request_id,
        user_id=user_id,
    )
    assert final is not None
    assert final.status == ChatGenerationStatus.SUCCEEDED
    assert final.attempt == 2
    assert final.dispatch_attempts == 1
    assert final.retryable is False
    assert final.error_code is None
    assert final.recovery_due_at is None


async def test_due_queued_redispatch_is_reserved_once_in_postgres(
    pg_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    repo, request, user_id, _, attempt = await _create_queued_request(
        pg_session,
        client_request_id="due-redispatch",
        recovery_due_at=now - timedelta(seconds=1),
    )
    request_id = request.id
    next_due = now + timedelta(minutes=5)

    due_requests = await repo.get_due_generation_requests(due_at=now, limit=10)
    assert [item.id for item in due_requests] == [request_id]
    assert (
        await repo.try_reserve_generation_request_redispatch(
            request_id=request_id,
            expected_attempt=attempt.attempt,
            task_id=attempt.task_id,
            lease_token=attempt.lease_token,
            expected_dispatch_attempts=1,
            max_dispatch_attempts=3,
            due_before=now,
            next_recovery_due_at=next_due,
        )
        == 2
    )
    assert (
        await repo.try_reserve_generation_request_redispatch(
            request_id=request_id,
            expected_attempt=attempt.attempt,
            task_id=attempt.task_id,
            lease_token=attempt.lease_token,
            expected_dispatch_attempts=1,
            max_dispatch_attempts=3,
            due_before=now,
            next_recovery_due_at=next_due,
        )
        is None
    )

    pg_session.expire_all()
    current = await repo.get_generation_request_for_actor(
        request_id=request_id,
        user_id=user_id,
    )
    assert current is not None
    assert current.status == ChatGenerationStatus.QUEUED
    assert current.attempt == 1
    assert current.dispatch_attempts == 2
    assert current.task_id == attempt.task_id
    assert current.lease_token == attempt.lease_token
    assert current.recovery_due_at == next_due


async def test_recovery_service_queues_due_prepared_request_in_postgres(
    pg_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    await _seed_scope(
        pg_session,
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )
    repo = ChatRepository(pg_session)
    request = await repo.create_generation_request(
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        client_request_id="prepared-service-recovery",
        dispatch_context=GenerationDispatchContext(
            mode="stream",
            generation_payload=GenerationPayload(
                session_id=session_id,
                query_text="question",
            ),
        ).model_dump(mode="json"),
        recovery_due_at=now - timedelta(seconds=1),
    )
    request_id = request.id
    dispatcher = AsyncMock()
    service = ChatGenerationRecoveryService(
        uow=cast(AbstractUnitOfWork, SessionBoundUow(pg_session)),
        dispatcher=dispatcher,
        recovery_seconds=300,
        max_dispatch_attempts=3,
        batch_size=10,
    )

    result = await service.reconcile_due_requests(now=now)

    assert result.prepared_dispatched_count == 1
    pg_session.expire_all()
    current = await pg_session.get(ChatGenerationRequest, request_id)
    assert current is not None
    assert current.status == ChatGenerationStatus.QUEUED
    assert current.dispatch_attempts == 1
    assert current.task_id is not None
    assert current.lease_token is not None
    dispatch_attempt = dispatcher.enqueue_generation_recovery.await_args.kwargs[
        "generation_attempt"
    ]
    assert dispatch_attempt.task_id == current.task_id
    assert dispatch_attempt.lease_token == current.lease_token


async def test_recovery_service_fails_exhausted_queue_and_message_in_postgres(
    pg_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    _, request, _, assistant_message_id, attempt = await _create_queued_request(
        pg_session,
        client_request_id="service-exhausted",
        recovery_due_at=now - timedelta(minutes=2),
    )
    request_id = request.id
    await pg_session.execute(
        text(
            "UPDATE chat_generation_requests "
            "SET dispatch_attempts = 3, recovery_due_at = :due_at "
            "WHERE id = :request_id"
        ),
        {"due_at": now - timedelta(seconds=1), "request_id": request_id},
    )
    pg_session.expire_all()
    dispatcher = AsyncMock()
    service = ChatGenerationRecoveryService(
        uow=cast(AbstractUnitOfWork, SessionBoundUow(pg_session)),
        dispatcher=dispatcher,
        recovery_seconds=300,
        max_dispatch_attempts=3,
        batch_size=10,
    )

    result = await service.reconcile_due_requests(now=now)

    assert result.failed_count == 1
    pg_session.expire_all()
    final_request = await pg_session.get(ChatGenerationRequest, request_id)
    final_message = await pg_session.get(ChatMessage, assistant_message_id)
    assert final_request is not None
    assert final_request.status == ChatGenerationStatus.FAILED
    assert final_request.retryable is True
    assert final_request.task_id == attempt.task_id
    assert final_message is not None
    assert final_message.status == MessageStatus.FAILED
    dispatcher.enqueue_generation_recovery.assert_not_awaited()


async def test_exhausted_queued_recovery_fences_late_delivery_in_postgres(
    pg_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    (
        repo,
        request,
        user_id,
        assistant_message_id,
        attempt,
    ) = await _create_queued_request(
        pg_session,
        client_request_id="exhausted-redispatch",
        recovery_due_at=now - timedelta(minutes=2),
    )
    request_id = request.id
    session_id = request.session_id
    assert (
        await repo.try_reserve_generation_request_redispatch(
            request_id=request_id,
            expected_attempt=1,
            task_id=attempt.task_id,
            lease_token=attempt.lease_token,
            expected_dispatch_attempts=1,
            max_dispatch_attempts=3,
            due_before=now - timedelta(minutes=1),
            next_recovery_due_at=now - timedelta(seconds=30),
        )
        == 2
    )
    assert (
        await repo.try_reserve_generation_request_redispatch(
            request_id=request_id,
            expected_attempt=1,
            task_id=attempt.task_id,
            lease_token=attempt.lease_token,
            expected_dispatch_attempts=2,
            max_dispatch_attempts=3,
            due_before=now,
            next_recovery_due_at=now + timedelta(minutes=1),
        )
        == 3
    )
    assert (
        await repo.try_reserve_generation_request_redispatch(
            request_id=request_id,
            expected_attempt=1,
            task_id=attempt.task_id,
            lease_token=attempt.lease_token,
            expected_dispatch_attempts=3,
            max_dispatch_attempts=3,
            due_before=now + timedelta(minutes=2),
            next_recovery_due_at=now + timedelta(minutes=7),
        )
        is None
    )
    assert await repo.try_fail_due_generation_request(
        request_id=request_id,
        expected_status=ChatGenerationStatus.QUEUED,
        expected_attempt=1,
        expected_dispatch_attempts=3,
        task_id=attempt.task_id,
        lease_token=attempt.lease_token,
        due_before=now + timedelta(minutes=2),
        finished_at=now + timedelta(minutes=2),
        error_code="CHAT_DISPATCH_RETRY_EXHAUSTED",
        error_message="生成任务派发失败，请重试",
    )
    assert not await repo.try_claim_generation_request(
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        expected_attempt=1,
        task_id=attempt.task_id,
        lease_token=attempt.lease_token,
        started_at=now + timedelta(minutes=3),
        lease_expires_at=now + timedelta(minutes=8),
    )

    pg_session.expire_all()
    final = await repo.get_generation_request_for_actor(
        request_id=request_id,
        user_id=user_id,
    )
    assert final is not None
    assert final.status == ChatGenerationStatus.FAILED
    assert final.retryable is True
    assert final.dispatch_attempts == 3
    assert final.error_code == "CHAT_DISPATCH_RETRY_EXHAUSTED"
    assert final.recovery_due_at is None


async def test_expired_running_recovery_fences_late_terminal_in_postgres(
    pg_session: AsyncSession,
) -> None:
    repo, request, _, attempt = await _create_running_request(
        pg_session,
        client_request_id="expired-running",
    )
    request_id = request.id
    finished_at = datetime.now(UTC) + timedelta(minutes=10)

    assert await repo.try_fail_due_generation_request(
        request_id=request_id,
        expected_status=ChatGenerationStatus.RUNNING,
        expected_attempt=attempt.attempt,
        expected_dispatch_attempts=1,
        task_id=attempt.task_id,
        lease_token=attempt.lease_token,
        due_before=finished_at,
        finished_at=finished_at,
        error_code="CHAT_GENERATION_LEASE_EXPIRED",
        error_message="生成任务执行超时，请重试",
    )
    assert not await repo.try_finalize_generation_request(
        request_id=request_id,
        expected_attempt=attempt.attempt,
        lease_token=attempt.lease_token,
        target_status=ChatGenerationStatus.SUCCEEDED,
        finished_at=finished_at + timedelta(seconds=1),
    )

    pg_session.expire_all()
    final = await pg_session.get(ChatGenerationRequest, request_id)
    assert final is not None
    assert final.status == ChatGenerationStatus.FAILED
    assert final.retryable is True
    assert final.error_code == "CHAT_GENERATION_LEASE_EXPIRED"
    assert final.dispatch_attempts == 1


async def test_worker_terminal_success_updates_message_and_request_atomically(
    pg_session: AsyncSession,
) -> None:
    repo, request, assistant_message_id, attempt = await _create_running_request(
        pg_session,
        client_request_id="atomic-success",
    )
    request_id = request.id
    handler = WorkerPersistenceHandler(
        uow=cast(AbstractUnitOfWork, SessionBoundUow(pg_session)),
        redis_client=cast(RedisClient, AsyncMock()),
    )

    await handler.persist_success(
        assistant_message_id=assistant_message_id,
        user_id=None,
        content="persisted answer",
        tokens_input=10,
        tokens_output=5,
        search_context=None,
        start_time=0.0,
        generation_attempt=attempt,
    )

    pg_session.expire_all()
    message = await repo.get_message(assistant_message_id)
    final = await pg_session.get(ChatGenerationRequest, request_id)
    assert message is not None
    assert message.status == MessageStatus.SUCCESS
    assert message.content == "persisted answer"
    assert final is not None
    assert final.status == ChatGenerationStatus.SUCCEEDED


async def test_stale_terminal_fence_rolls_back_message_update(
    pg_session: AsyncSession,
) -> None:
    repo, request, assistant_message_id, attempt = await _create_running_request(
        pg_session,
        client_request_id="atomic-stale",
    )
    request_id = request.id
    handler = WorkerPersistenceHandler(
        uow=cast(AbstractUnitOfWork, SessionBoundUow(pg_session)),
        redis_client=cast(RedisClient, AsyncMock()),
    )
    stale_attempt = attempt.model_copy(update={"lease_token": "stale-lease"})

    with pytest.raises(GenerationAttemptRejected):
        await handler.persist_success(
            assistant_message_id=assistant_message_id,
            user_id=None,
            content="late answer",
            tokens_input=10,
            tokens_output=5,
            search_context=None,
            start_time=0.0,
            generation_attempt=stale_attempt,
        )

    pg_session.expire_all()
    message = await repo.get_message(assistant_message_id)
    current = await pg_session.get(ChatGenerationRequest, request_id)
    assert message is not None
    assert message.status == MessageStatus.THINKING
    assert message.content == ""
    assert current is not None
    assert current.status == ChatGenerationStatus.RUNNING


async def test_actor_queries_require_live_workspace_membership_and_session(
    pg_session: AsyncSession,
) -> None:
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    session_owner_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    await _seed_scope(
        pg_session,
        user_id=user_id,
        workspace_id=workspace_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )
    await pg_session.execute(
        text("INSERT INTO users (id) VALUES (:other_id), (:owner_id)"),
        {"other_id": other_user_id, "owner_id": session_owner_id},
    )
    await pg_session.execute(
        text("UPDATE chat_sessions SET user_id = :owner_id WHERE id = :id"),
        {"owner_id": session_owner_id, "id": session_id},
    )
    repo = ChatRepository(pg_session)
    request = await repo.create_generation_request(
        user_id=user_id,
        workspace_id=workspace_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        client_request_id="authorized-request",
    )

    assert (
        await repo.get_generation_request_for_actor(
            request_id=request.id,
            user_id=user_id,
        )
        is not None
    )
    assert (
        await repo.get_generation_request_by_client_request_id_for_actor(
            user_id=user_id,
            client_request_id="authorized-request",
        )
        is not None
    )
    assert (
        await repo.get_generation_request_for_actor(
            request_id=request.id,
            user_id=other_user_id,
        )
        is None
    )
    assert not await repo.try_queue_generation_request(
        request_id=request.id,
        user_id=other_user_id,
        expected_attempt=1,
        task_id="unauthorized-task",
        lease_token="unauthorized-lease",
        queued_at=datetime.now(UTC),
        recovery_due_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    await pg_session.execute(
        text(
            "DELETE FROM user_workspace_roles "
            "WHERE user_id = :user_id AND workspace_id = :workspace_id"
        ),
        {"user_id": user_id, "workspace_id": workspace_id},
    )
    assert (
        await repo.get_generation_request_for_actor(
            request_id=request.id,
            user_id=user_id,
        )
        is None
    )

    await pg_session.execute(
        text(
            "INSERT INTO user_workspace_roles (id, user_id, workspace_id) "
            "VALUES (:id, :user_id, :workspace_id)"
        ),
        {"id": uuid.uuid4(), "user_id": user_id, "workspace_id": workspace_id},
    )
    await pg_session.execute(
        text("UPDATE workspaces SET deleted_at = now() WHERE id = :id"),
        {"id": workspace_id},
    )
    assert (
        await repo.get_generation_request_for_actor(
            request_id=request.id,
            user_id=user_id,
        )
        is None
    )

    await pg_session.execute(
        text("UPDATE workspaces SET deleted_at = NULL WHERE id = :id"),
        {"id": workspace_id},
    )
    await pg_session.execute(
        text("UPDATE chat_sessions SET deleted_at = now() WHERE id = :id"),
        {"id": session_id},
    )
    assert (
        await repo.get_generation_request_for_actor(
            request_id=request.id,
            user_id=user_id,
        )
        is None
    )
