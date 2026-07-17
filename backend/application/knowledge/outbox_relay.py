"""Durable Knowledge ingestion outbox relay.

职责：claim 到期 outbox、经 AbstractTaskDispatcher 至少一次投递，并确认发布结果。
边界：不执行 ingestion、不把 Redis 当业务事实源，也不抽象 Chat 的恢复状态机。
副作用：短事务更新 PostgreSQL，并向 TaskIQ broker 写入稳定 message identity。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractTaskDispatcher, AbstractUnitOfWork
from backend.models.orm.knowledge import FileStatus
from backend.models.orm.task import TaskOutbox, TaskOutboxStatus, TaskStatus
from backend.models.schemas.knowledge_schema import KnowledgeIngestionDispatchPayload

logger = logging.getLogger(__name__)

INVALID_PAYLOAD_ERROR = "KNOWLEDGE_OUTBOX_INVALID_PAYLOAD"
PUBLISH_EXHAUSTED_ERROR = "KNOWLEDGE_OUTBOX_PUBLISH_EXHAUSTED"


class _ReplayConflict(RuntimeError):
    pass


@dataclass(slots=True)
class KnowledgeOutboxRelayResult:
    claimed_count: int = 0
    published_count: int = 0
    retry_count: int = 0
    dead_count: int = 0
    conflict_count: int = 0


class KnowledgeOutboxRelayService:
    """Bounded, lease-fenced publisher for Knowledge ingestion events."""

    def __init__(
        self,
        *,
        uow: AbstractUnitOfWork,
        dispatcher: AbstractTaskDispatcher,
        retry_seconds: int | None = None,
        lease_seconds: int | None = None,
        max_attempts: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.uow = uow
        self.dispatcher = dispatcher
        self.retry_seconds = (
            retry_seconds
            if retry_seconds is not None
            else ai_settings.KNOWLEDGE_OUTBOX_RETRY_SECONDS
        )
        self.lease_seconds = (
            lease_seconds
            if lease_seconds is not None
            else ai_settings.KNOWLEDGE_OUTBOX_LEASE_SECONDS
        )
        self.max_attempts = (
            max_attempts
            if max_attempts is not None
            else ai_settings.KNOWLEDGE_OUTBOX_MAX_ATTEMPTS
        )
        self.batch_size = (
            batch_size
            if batch_size is not None
            else ai_settings.KNOWLEDGE_RECOVERY_BATCH_SIZE
        )

    async def relay_due(
        self,
        *,
        now: datetime | None = None,
    ) -> KnowledgeOutboxRelayResult:
        current_time = now or datetime.now(UTC)
        lease_owner = uuid.uuid4().hex
        lease_expires_at = current_time + timedelta(seconds=self.lease_seconds)
        async with self.uow:
            claimed = await self.uow.task_outbox_repo.claim_due_batch(
                due_at=current_time,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                max_attempts=self.max_attempts,
                limit=self.batch_size,
            )

        result = KnowledgeOutboxRelayResult(claimed_count=len(claimed))
        for outbox in claimed:
            await self._publish_claimed(
                outbox,
                lease_owner=lease_owner,
                current_time=current_time,
                result=result,
            )
        await self._mark_exhausted(current_time=current_time, result=result)
        return result

    async def publish_one(
        self,
        *,
        outbox_id: uuid.UUID,
        now: datetime | None = None,
    ) -> KnowledgeOutboxRelayResult:
        """Best-effort post-commit fast publish; failure remains durably retryable."""
        current_time = now or datetime.now(UTC)
        lease_owner = uuid.uuid4().hex
        async with self.uow:
            claimed = await self.uow.task_outbox_repo.try_claim(
                outbox_id=outbox_id,
                due_at=current_time,
                lease_owner=lease_owner,
                lease_expires_at=current_time + timedelta(seconds=self.lease_seconds),
                max_attempts=self.max_attempts,
            )
        result = KnowledgeOutboxRelayResult(claimed_count=int(claimed is not None))
        if claimed is None:
            result.conflict_count += 1
            return result
        await self._publish_claimed(
            claimed,
            lease_owner=lease_owner,
            current_time=current_time,
            result=result,
        )
        return result

    async def replay_dead(
        self,
        *,
        outbox_id: uuid.UUID,
        expected_attempt: int,
        now: datetime | None = None,
    ) -> bool:
        """Atomically re-open a DEAD pre-processing delivery for manual replay."""
        current_time = now or datetime.now(UTC)
        try:
            async with self.uow:
                outbox = await self.uow.task_outbox_repo.get(outbox_id)
                if (
                    outbox is None
                    or TaskOutboxStatus(outbox.status) != TaskOutboxStatus.DEAD
                    or outbox.attempt_count != expected_attempt
                ):
                    raise _ReplayConflict
                try:
                    payload = KnowledgeIngestionDispatchPayload.model_validate(
                        outbox.payload
                    )
                except (TypeError, ValidationError) as exc:
                    raise _ReplayConflict from exc
                task = await self.uow.task_repo.get(payload.task_id)
                file_obj = await self.uow.knowledge_repo.get_file(payload.file_id)
                if task is None or file_obj is None:
                    raise _ReplayConflict

                task_status = TaskStatus(task.status)
                file_status = FileStatus(file_obj.status)
                if task_status == TaskStatus.FAILED:
                    if file_status != FileStatus.FAILED:
                        raise _ReplayConflict
                    task_reset = (
                        await self.uow.task_repo.try_prepare_failed_kb_ingestion_replay(
                            task_id=task.id,
                            expected_attempt=task.attempt_count,
                        )
                    )
                    if not task_reset:
                        raise _ReplayConflict
                    await self.uow.knowledge_repo.delete_chunks_for_file(file_obj.id)
                    file_reset = (
                        await self.uow.knowledge_repo.try_transition_file_status(
                            file_id=file_obj.id,
                            expected_previous_statuses=(FileStatus.FAILED,),
                            target_status=FileStatus.UPLOADED,
                        )
                    )
                    if not file_reset:
                        raise _ReplayConflict
                elif not (
                    task_status == TaskStatus.PENDING
                    and file_status == FileStatus.UPLOADED
                ):
                    raise _ReplayConflict

                replayed = await self.uow.task_outbox_repo.try_prepare_replay(
                    outbox_id=outbox_id,
                    expected_status=TaskOutboxStatus.DEAD,
                    expected_attempt=expected_attempt,
                    next_attempt_at=current_time,
                    reset_attempts=True,
                )
                if not replayed:
                    raise _ReplayConflict
        except _ReplayConflict:
            return False
        return True

    async def _publish_claimed(
        self,
        outbox: TaskOutbox,
        *,
        lease_owner: str,
        current_time: datetime,
        result: KnowledgeOutboxRelayResult,
    ) -> None:
        try:
            payload = KnowledgeIngestionDispatchPayload.model_validate(outbox.payload)
        except (TypeError, ValidationError):
            await self._release(
                outbox,
                lease_owner=lease_owner,
                current_time=current_time,
                error=INVALID_PAYLOAD_ERROR,
                result=result,
            )
            return

        try:
            await self.dispatcher.enqueue_ingestion(
                str(payload.file_id),
                str(payload.task_id),
                payload.trace_context,
                outbox_id=str(outbox.id),
                message_id=str(outbox.id),
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: broker publish failed"
            logger.exception(
                "Knowledge outbox broker publish failed",
                extra=self._log_context(
                    outbox,
                    event="knowledge_outbox_publish_failed",
                ),
            )
            await self._release(
                outbox,
                lease_owner=lease_owner,
                current_time=current_time,
                error=error,
                result=result,
            )
            return

        async with self.uow:
            published = await self.uow.task_outbox_repo.try_mark_published(
                outbox_id=outbox.id,
                expected_attempt=outbox.attempt_count,
                lease_owner=lease_owner,
                published_at=current_time,
            )
        if published:
            result.published_count += 1
            logger.info(
                "Knowledge outbox published",
                extra=self._log_context(
                    outbox,
                    event="knowledge_outbox_published",
                    outbox_status=TaskOutboxStatus.PUBLISHED,
                ),
            )
        else:
            result.conflict_count += 1

    async def _release(
        self,
        outbox: TaskOutbox,
        *,
        lease_owner: str,
        current_time: datetime,
        error: str,
        result: KnowledgeOutboxRelayResult,
    ) -> None:
        async with self.uow:
            released = await self.uow.task_outbox_repo.try_release_for_retry(
                outbox_id=outbox.id,
                expected_attempt=outbox.attempt_count,
                lease_owner=lease_owner,
                next_attempt_at=current_time + timedelta(seconds=self.retry_seconds),
                last_error=error,
            )
        if released:
            result.retry_count += 1
        else:
            result.conflict_count += 1

    async def _mark_exhausted(
        self,
        *,
        current_time: datetime,
        result: KnowledgeOutboxRelayResult,
    ) -> None:
        async with self.uow.read_context():
            exhausted = await self.uow.task_outbox_repo.get_exhausted_due(
                due_at=current_time,
                max_attempts=self.max_attempts,
                limit=self.batch_size,
            )
        for outbox in exhausted:
            async with self.uow:
                marked = await self.uow.task_outbox_repo.try_mark_dead(
                    outbox_id=outbox.id,
                    expected_attempt=outbox.attempt_count,
                    due_before=current_time,
                    last_error=PUBLISH_EXHAUSTED_ERROR,
                )
            if not marked:
                result.conflict_count += 1
                continue
            result.dead_count += 1
            logger.error(
                "Knowledge outbox publish budget exhausted",
                extra={
                    **self._log_context(
                        outbox,
                        event="knowledge_outbox_dead",
                        outbox_status=TaskOutboxStatus.DEAD,
                    ),
                    "error_code": PUBLISH_EXHAUSTED_ERROR,
                },
            )

    @staticmethod
    def _log_context(
        outbox: TaskOutbox,
        *,
        event: str,
        outbox_status: TaskOutboxStatus | None = None,
    ) -> dict[str, object]:
        return {
            "event": event,
            "outbox_id": str(outbox.id),
            "task_id": str(outbox.task_id),
            "event_type": outbox.event_type,
            "outbox_status": str(outbox_status or outbox.status),
            "previous_outbox_status": str(outbox.status),
            "publish_attempt": outbox.attempt_count,
            "next_attempt_at": outbox.next_attempt_at,
            "lease_expires_at": outbox.lease_expires_at,
        }
