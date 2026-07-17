"""Real PostgreSQL contracts for durable Knowledge ingestion.

职责：验证 worker attempt CAS、终态单调性、outbox lease/发布和稳定事件唯一性。
边界：使用隔离 schema，不运行应用迁移、不触碰现有业务数据或 Redis。
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import redis.asyncio as redis
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.application.knowledge.outbox_relay import KnowledgeOutboxRelayService
from backend.config.settings import settings
from backend.infra.task_dispatcher import TaskDispatcher
from backend.models.orm.task import (
    KNOWLEDGE_INGESTION_EVENT,
    TaskJob,
    TaskOutbox,
    TaskOutboxStatus,
    TaskStatus,
)
from backend.repositories.task_outbox_repo import TaskOutboxRepository
from backend.repositories.task_repo import TaskRepository
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
    engine = create_async_engine(
        _postgres_url(),
        connect_args=settings.database_connect_args,
        pool_pre_ping=True,
    )
    schema = f"ws4_{uuid.uuid4().hex}"
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
                    "CREATE TABLE knowledge_bases (id UUID PRIMARY KEY)",
                    """
                    CREATE TABLE knowledge_files (
                        id UUID PRIMARY KEY,
                        kb_id UUID NOT NULL REFERENCES knowledge_bases(id)
                    )
                    """,
                ):
                    await connection.execute(text(ddl))
                await connection.run_sync(TaskJob.__table__.create)
                await connection.run_sync(TaskOutbox.__table__.create)
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


async def _seed_job(
    session: AsyncSession,
) -> tuple[TaskRepository, TaskOutboxRepository, TaskJob, uuid.UUID]:
    kb_id = uuid.uuid4()
    file_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO knowledge_bases (id) VALUES (:id)"), {"id": kb_id}
    )
    await session.execute(
        text("INSERT INTO knowledge_files (id, kb_id) VALUES (:id, :kb_id)"),
        {"id": file_id, "kb_id": kb_id},
    )
    task_repo = TaskRepository(session)
    outbox_repo = TaskOutboxRepository(session)
    task = await task_repo.create(
        action_type="KB_INGESTION",
        payload={"file_id": str(file_id), "kb_id": str(kb_id)},
        knowledge_file_id=file_id,
        knowledge_base_id=kb_id,
    )
    return task_repo, outbox_repo, task, file_id


class SessionBoundUow:
    """Nested transaction UoW for a fixture-owned real PostgreSQL session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.task_repo = TaskRepository(session)
        self.task_outbox_repo = TaskOutboxRepository(session)
        self._transaction = None

    async def __aenter__(self):
        self._transaction = await self.session.begin_nested()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        assert self._transaction is not None
        if exc_type is None:
            await self._transaction.commit()
        else:
            await self._transaction.rollback()
        self._transaction = None

    @asynccontextmanager
    async def read_context(self):
        yield self


async def test_worker_attempt_fences_duplicate_and_late_terminal_writes(
    pg_session: AsyncSession,
) -> None:
    task_repo, _, task, file_id = await _seed_job(pg_session)
    now = datetime(2026, 7, 17, tzinfo=UTC)

    first_attempt = await task_repo.try_claim_kb_ingestion_task(
        task_id=task.id,
        file_id=file_id,
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )
    duplicate_claim = await task_repo.try_claim_kb_ingestion_task(
        task_id=task.id,
        file_id=file_id,
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )
    assert first_attempt == 1
    assert duplicate_claim is None

    assert await task_repo.try_reset_expired_kb_ingestion_task(
        task_id=task.id,
        expected_attempt=1,
        lease_expired_before=now + timedelta(minutes=6),
        legacy_updated_before=now,
        error_log="expired",
    )
    second_attempt = await task_repo.try_claim_kb_ingestion_task(
        task_id=task.id,
        file_id=file_id,
        claimed_at=now + timedelta(minutes=6),
        lease_expires_at=now + timedelta(minutes=11),
    )
    assert second_attempt == 2
    assert not await task_repo.try_complete_kb_ingestion_task(
        task_id=task.id,
        expected_attempt=1,
        finished_at=now + timedelta(minutes=7),
    )
    assert await task_repo.try_complete_kb_ingestion_task(
        task_id=task.id,
        expected_attempt=2,
        finished_at=now + timedelta(minutes=7),
    )
    assert (
        await task_repo.try_claim_kb_ingestion_task(
            task_id=task.id,
            file_id=file_id,
            claimed_at=now,
            lease_expires_at=now + timedelta(minutes=5),
        )
        is None
    )


async def test_outbox_claim_publish_and_unique_business_event(
    pg_session: AsyncSession,
) -> None:
    _, outbox_repo, task, file_id = await _seed_job(pg_session)
    now = datetime(2026, 7, 17, tzinfo=UTC)
    outbox = await outbox_repo.create(
        task_id=task.id,
        event_type=KNOWLEDGE_INGESTION_EVENT,
        payload={"file_id": str(file_id), "task_id": str(task.id)},
        next_attempt_at=now,
    )

    claimed = await outbox_repo.claim_due_batch(
        due_at=now,
        lease_owner="relay-a",
        lease_expires_at=now + timedelta(minutes=1),
        max_attempts=3,
        limit=10,
    )
    assert [row.id for row in claimed] == [outbox.id]
    assert claimed[0].attempt_count == 1
    assert await outbox_repo.try_mark_published(
        outbox_id=outbox.id,
        expected_attempt=1,
        lease_owner="relay-a",
        published_at=now,
    )
    persisted = await pg_session.scalar(
        select(TaskOutbox).where(TaskOutbox.id == outbox.id)
    )
    assert persisted is not None
    assert TaskOutboxStatus(persisted.status) == TaskOutboxStatus.PUBLISHED

    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            duplicate = TaskOutbox(
                task_id=task.id,
                event_type=KNOWLEDGE_INGESTION_EVENT,
                payload={},
                status=TaskOutboxStatus.PENDING,
                attempt_count=0,
                next_attempt_at=now,
            )
            pg_session.add(duplicate)
            await pg_session.flush()


async def test_active_task_per_file_is_unique_in_postgres(
    pg_session: AsyncSession,
) -> None:
    task_repo, _, task, file_id = await _seed_job(pg_session)

    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await task_repo.create(
                action_type="KB_INGESTION",
                payload={"file_id": str(file_id)},
                status=TaskStatus.PENDING,
                knowledge_file_id=file_id,
                knowledge_base_id=task.knowledge_base_id,
            )
            await pg_session.flush()


@pytest.mark.requires_taskiq
@pytest.mark.requires_redis
async def test_real_redis_fast_publish_confirms_the_postgres_outbox(
    pg_session: AsyncSession,
) -> None:
    _, outbox_repo, task, file_id = await _seed_job(pg_session)
    now = datetime.now(UTC)
    outbox = await outbox_repo.create(
        task_id=task.id,
        event_type=KNOWLEDGE_INGESTION_EVENT,
        payload={
            "file_id": str(file_id),
            "task_id": str(task.id),
            "trace_context": None,
        },
        next_attempt_at=now,
    )
    redis_client = redis.from_url(require_env("TEST_TASKIQ_REDIS_URL"))
    try:
        await redis_client.delete("taskiq")
        service = KnowledgeOutboxRelayService(
            uow=SessionBoundUow(pg_session),
            dispatcher=TaskDispatcher(redis_client),
            max_attempts=3,
        )

        result = await service.publish_one(outbox_id=outbox.id, now=now)

        assert result.published_count == 1
        raw_message = await redis_client.lindex("taskiq", 0)
        assert raw_message is not None
        message = json.loads(raw_message)
        assert message["task_id"] == str(outbox.id)
        assert message["args"] == [
            str(file_id),
            str(task.id),
            None,
            str(outbox.id),
        ]
        await pg_session.refresh(outbox)
        assert TaskOutboxStatus(outbox.status) == TaskOutboxStatus.PUBLISHED
    finally:
        await redis_client.delete("taskiq")
        await redis_client.aclose()
