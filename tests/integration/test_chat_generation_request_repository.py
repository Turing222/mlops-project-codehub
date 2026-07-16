"""Real PostgreSQL contracts for durable Chat generation requests.

职责：验证 actor-scoped 唯一性、attempt/lease CAS 和 Workspace/session 授权；
边界：在一次事务内创建隔离 schema，不运行应用迁移、不触碰现有业务数据。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.config.settings import settings
from backend.models.enums import ChatGenerationStatus
from backend.models.orm.chat import ChatGenerationRequest
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
                    "CREATE TABLE chat_messages (id UUID PRIMARY KEY)",
                    """
                    CREATE TABLE user_workspace_roles (
                        id UUID PRIMARY KEY,
                        user_id UUID NOT NULL,
                        workspace_id UUID NOT NULL
                    )
                    """,
                ):
                    await connection.execute(text(ddl))
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
            "INSERT INTO chat_messages (id) "
            "VALUES (:user_message_id), (:assistant_message_id)"
        ),
        {
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
        },
    )


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
        expected_attempt=1,
        lease_token="wrong-lease",
        started_at=now,
        lease_expires_at=now + timedelta(minutes=2),
    )
    assert await repo.try_claim_generation_request(
        request_id=request.id,
        expected_attempt=1,
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
            recovery_due_at=now + timedelta(minutes=4),
        )
        == 2
    )
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
        expected_attempt=2,
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
    assert final.retryable is False
    assert final.error_code is None
    assert final.recovery_due_at is None


async def test_actor_queries_require_live_workspace_membership_and_session(
    pg_session: AsyncSession,
) -> None:
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
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
        text("INSERT INTO users (id) VALUES (:id)"),
        {"id": other_user_id},
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
