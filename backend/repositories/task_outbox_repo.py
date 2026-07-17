"""Transactional task outbox repository.

职责：创建稳定业务事件、以 SKIP LOCKED 批量 claim，并用 lease CAS 确认发布结果。
边界：不连接 broker、不解释事件 payload，也不决定任务重试策略。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.task import TaskOutbox, TaskOutboxStatus
from backend.repositories.base import CRUDBase


class TaskOutboxRepository:
    """Persist and fence at-least-once task publication."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.crud: CRUDBase[TaskOutbox, BaseModel, BaseModel] = CRUDBase(
            TaskOutbox, session
        )

    async def get(self, outbox_id: uuid.UUID) -> TaskOutbox | None:
        return await self.crud.get(outbox_id)

    async def get_for_task_event(
        self,
        *,
        task_id: uuid.UUID,
        event_type: str,
    ) -> TaskOutbox | None:
        stmt = select(TaskOutbox).where(
            TaskOutbox.task_id == task_id,
            TaskOutbox.event_type == event_type,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        task_id: uuid.UUID,
        event_type: str,
        payload: dict,
        next_attempt_at: datetime,
    ) -> TaskOutbox:
        return await self.crud.create(
            obj_in={
                "task_id": task_id,
                "event_type": event_type,
                "payload": payload,
                "status": TaskOutboxStatus.PENDING,
                "attempt_count": 0,
                "next_attempt_at": next_attempt_at,
            }
        )

    async def claim_due_batch(
        self,
        *,
        due_at: datetime,
        lease_owner: str,
        lease_expires_at: datetime,
        max_attempts: int,
        limit: int,
    ) -> Sequence[TaskOutbox]:
        """Claim one bounded batch; concurrent relays skip rows already locked."""
        if not lease_owner.strip():
            raise ValueError("lease_owner must not be blank")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")

        due_pending = and_(
            TaskOutbox.status == TaskOutboxStatus.PENDING,
            TaskOutbox.next_attempt_at.is_not(None),
            TaskOutbox.next_attempt_at <= due_at,
        )
        expired_publish = and_(
            TaskOutbox.status == TaskOutboxStatus.PUBLISHING,
            TaskOutbox.lease_expires_at.is_not(None),
            TaskOutbox.lease_expires_at <= due_at,
        )
        stmt = (
            select(TaskOutbox)
            .where(
                or_(due_pending, expired_publish),
                TaskOutbox.attempt_count < max_attempts,
            )
            .order_by(TaskOutbox.next_attempt_at.asc(), TaskOutbox.id.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        for row in rows:
            row.status = TaskOutboxStatus.PUBLISHING
            row.attempt_count += 1
            row.lease_owner = lease_owner
            row.lease_expires_at = lease_expires_at
            row.next_attempt_at = lease_expires_at
            self.session.add(row)
        await self.session.flush()
        return rows

    async def try_claim(
        self,
        *,
        outbox_id: uuid.UUID,
        due_at: datetime,
        lease_owner: str,
        lease_expires_at: datetime,
        max_attempts: int,
    ) -> TaskOutbox | None:
        """CAS one specific due event for the post-commit fast-publish path."""
        due_condition = or_(
            and_(
                TaskOutbox.status == TaskOutboxStatus.PENDING,
                TaskOutbox.next_attempt_at.is_not(None),
                TaskOutbox.next_attempt_at <= due_at,
            ),
            and_(
                TaskOutbox.status == TaskOutboxStatus.PUBLISHING,
                TaskOutbox.lease_expires_at.is_not(None),
                TaskOutbox.lease_expires_at <= due_at,
            ),
        )
        stmt = (
            update(TaskOutbox)
            .where(
                TaskOutbox.id == outbox_id,
                due_condition,
                TaskOutbox.attempt_count < max_attempts,
            )
            .values(
                status=TaskOutboxStatus.PUBLISHING,
                attempt_count=TaskOutbox.attempt_count + 1,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                next_attempt_at=lease_expires_at,
            )
            .returning(TaskOutbox)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_exhausted_due(
        self,
        *,
        due_at: datetime,
        max_attempts: int,
        limit: int,
    ) -> Sequence[TaskOutbox]:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        stmt = (
            select(TaskOutbox)
            .where(
                TaskOutbox.status.in_(
                    (TaskOutboxStatus.PENDING, TaskOutboxStatus.PUBLISHING)
                ),
                TaskOutbox.attempt_count >= max_attempts,
                or_(
                    and_(
                        TaskOutbox.status == TaskOutboxStatus.PENDING,
                        TaskOutbox.next_attempt_at.is_not(None),
                        TaskOutbox.next_attempt_at <= due_at,
                    ),
                    and_(
                        TaskOutbox.status == TaskOutboxStatus.PUBLISHING,
                        TaskOutbox.lease_expires_at.is_not(None),
                        TaskOutbox.lease_expires_at <= due_at,
                    ),
                ),
            )
            .order_by(TaskOutbox.next_attempt_at.asc(), TaskOutbox.id.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def try_mark_published(
        self,
        *,
        outbox_id: uuid.UUID,
        expected_attempt: int,
        lease_owner: str,
        published_at: datetime,
    ) -> bool:
        stmt = (
            update(TaskOutbox)
            .where(
                TaskOutbox.id == outbox_id,
                TaskOutbox.status == TaskOutboxStatus.PUBLISHING,
                TaskOutbox.attempt_count == expected_attempt,
                TaskOutbox.lease_owner == lease_owner,
            )
            .values(
                status=TaskOutboxStatus.PUBLISHED,
                next_attempt_at=None,
                lease_owner=None,
                lease_expires_at=None,
                published_at=published_at,
                last_error=None,
            )
            .returning(TaskOutbox.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_release_for_retry(
        self,
        *,
        outbox_id: uuid.UUID,
        expected_attempt: int,
        lease_owner: str,
        next_attempt_at: datetime,
        last_error: str,
    ) -> bool:
        stmt = (
            update(TaskOutbox)
            .where(
                TaskOutbox.id == outbox_id,
                TaskOutbox.status == TaskOutboxStatus.PUBLISHING,
                TaskOutbox.attempt_count == expected_attempt,
                TaskOutbox.lease_owner == lease_owner,
            )
            .values(
                status=TaskOutboxStatus.PENDING,
                next_attempt_at=next_attempt_at,
                lease_owner=None,
                lease_expires_at=None,
                last_error=last_error[:5000],
            )
            .returning(TaskOutbox.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_mark_dead(
        self,
        *,
        outbox_id: uuid.UUID,
        expected_attempt: int,
        due_before: datetime,
        last_error: str,
    ) -> bool:
        stmt = (
            update(TaskOutbox)
            .where(
                TaskOutbox.id == outbox_id,
                TaskOutbox.status.in_(
                    (TaskOutboxStatus.PENDING, TaskOutboxStatus.PUBLISHING)
                ),
                TaskOutbox.attempt_count == expected_attempt,
                or_(
                    and_(
                        TaskOutbox.next_attempt_at.is_not(None),
                        TaskOutbox.next_attempt_at <= due_before,
                    ),
                    and_(
                        TaskOutbox.lease_expires_at.is_not(None),
                        TaskOutbox.lease_expires_at <= due_before,
                    ),
                ),
            )
            .values(
                status=TaskOutboxStatus.DEAD,
                next_attempt_at=None,
                lease_owner=None,
                lease_expires_at=None,
                last_error=last_error[:5000],
            )
            .returning(TaskOutbox.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def try_prepare_replay(
        self,
        *,
        outbox_id: uuid.UUID,
        expected_status: TaskOutboxStatus,
        expected_attempt: int,
        next_attempt_at: datetime,
        reset_attempts: bool = False,
    ) -> bool:
        """CAS a published gap or manually selected DEAD event back to PENDING."""
        if expected_status not in {
            TaskOutboxStatus.PUBLISHED,
            TaskOutboxStatus.DEAD,
        }:
            raise ValueError("only published or dead outbox events can be replayed")
        values: dict[str, object] = {
            "status": TaskOutboxStatus.PENDING,
            "next_attempt_at": next_attempt_at,
            "lease_owner": None,
            "lease_expires_at": None,
            "published_at": None,
            "last_error": None,
        }
        if reset_attempts:
            values["attempt_count"] = 0
        stmt = (
            update(TaskOutbox)
            .where(
                TaskOutbox.id == outbox_id,
                TaskOutbox.status == expected_status,
                TaskOutbox.attempt_count == expected_attempt,
            )
            .values(**values)
            .returning(TaskOutbox.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
