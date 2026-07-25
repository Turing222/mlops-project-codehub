"""Task outbox repository unit tests.

职责：验证 SKIP LOCKED claim、attempt/lease 更新和发布确认 CAS。
边界：不连接真实 PostgreSQL。
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from backend.models.orm.task import TaskOutbox, TaskOutboxStatus
from backend.repositories.task_outbox_repo import TaskOutboxRepository


async def test_get_oldest_due_at_uses_pending_and_expired_publish_facts() -> None:
    session = AsyncMock()
    due_at = datetime(2026, 7, 17, tzinfo=UTC)
    expected = due_at - timedelta(minutes=2)
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = expected
    session.execute.return_value = result_proxy
    repo = TaskOutboxRepository(session)

    observed = await repo.get_oldest_due_at(due_at=due_at)

    assert observed == expected
    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "task_outbox.status = 'pending'" in sql
    assert "task_outbox.next_attempt_at" in sql
    assert "task_outbox.lease_expires_at" in sql


async def test_claim_due_batch_sets_publish_lease_and_increments_attempt() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    row = TaskOutbox(
        id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        event_type="knowledge.ingestion.requested",
        payload={},
        status=TaskOutboxStatus.PENDING,
        attempt_count=0,
        next_attempt_at=datetime(2026, 7, 17, tzinfo=UTC),
    )
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = [row]
    session.execute.return_value = result_proxy
    repo = TaskOutboxRepository(session)
    now = datetime(2026, 7, 17, 1, tzinfo=UTC)
    lease_expires = now + timedelta(minutes=1)

    claimed = await repo.claim_due_batch(
        due_at=now,
        lease_owner="relay-a",
        lease_expires_at=lease_expires,
        max_attempts=3,
        limit=100,
    )

    assert claimed == [row]
    assert row.status == TaskOutboxStatus.PUBLISHING
    assert row.attempt_count == 1
    assert row.lease_owner == "relay-a"
    assert row.lease_expires_at == lease_expires
    stmt = session.execute.await_args.args[0]
    assert stmt._for_update_arg.skip_locked is True


async def test_mark_published_requires_attempt_and_lease_owner() -> None:
    session = AsyncMock()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = uuid.uuid4()
    session.execute.return_value = result_proxy
    repo = TaskOutboxRepository(session)

    published = await repo.try_mark_published(
        outbox_id=uuid.uuid4(),
        expected_attempt=2,
        lease_owner="relay-a",
        published_at=datetime(2026, 7, 17, tzinfo=UTC),
    )

    assert published is True
    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "task_outbox.attempt_count = 2" in sql
    assert "task_outbox.lease_owner = 'relay-a'" in sql
    assert "status='published'" in sql


async def test_release_for_retry_preserves_attempt_and_records_sanitized_error() -> (
    None
):
    session = AsyncMock()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = uuid.uuid4()
    session.execute.return_value = result_proxy
    repo = TaskOutboxRepository(session)

    released = await repo.try_release_for_retry(
        outbox_id=uuid.uuid4(),
        expected_attempt=1,
        lease_owner="relay-a",
        next_attempt_at=datetime(2026, 7, 17, tzinfo=UTC),
        last_error="ConnectionError: broker publish failed",
    )

    assert released is True
    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "status='pending'" in sql
    assert "last_error='ConnectionError: broker publish failed'" in sql
