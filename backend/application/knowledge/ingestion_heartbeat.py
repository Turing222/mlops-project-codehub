"""Worker-side heartbeat for one Knowledge ingestion attempt.

职责：使用独立 UoW 周期续租当前 TaskJob attempt，并在 CAS fence 失效后停止。
边界：不改变 File 状态、不重派任务、不提交任务终态。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractUnitOfWork

logger = logging.getLogger(__name__)


class IngestionLeaseHeartbeat:
    """Renew one stable Knowledge job attempt without sharing its work UoW."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        task_id: uuid.UUID,
        expected_attempt: int,
        interval_seconds: float | None = None,
        lease_seconds: int | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._task_id = task_id
        self._expected_attempt = expected_attempt
        self._interval_seconds = (
            interval_seconds
            if interval_seconds is not None
            else ai_settings.KNOWLEDGE_INGEST_HEARTBEAT_SECONDS
        )
        self._lease_seconds = (
            lease_seconds
            if lease_seconds is not None
            else ai_settings.KNOWLEDGE_INGEST_LEASE_SECONDS
        )
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.lease_lost = False

    async def start(self) -> bool:
        if not await self._renew():
            self.lease_lost = True
            return False
        self._task = asyncio.create_task(
            self._run(),
            name=f"knowledge-heartbeat-{self._task_id}",
        )
        return True

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        try:
            await self._task
        except Exception:
            logger.warning(
                "Knowledge ingestion heartbeat failed during shutdown",
                extra=self._log_context("knowledge_ingestion_heartbeat_shutdown_error"),
                exc_info=True,
            )
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set() and not self.lease_lost:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._interval_seconds
                )
            if self._stop_event.is_set():
                return
            try:
                renewed = await self._renew()
            except Exception:
                logger.warning(
                    "Knowledge ingestion heartbeat write failed",
                    extra=self._log_context("knowledge_ingestion_heartbeat_error"),
                    exc_info=True,
                )
                continue
            if not renewed:
                self.lease_lost = True
                logger.warning(
                    "Knowledge ingestion heartbeat fence rejected",
                    extra=self._log_context("knowledge_ingestion_heartbeat_rejected"),
                )

    async def _renew(self) -> bool:
        heartbeat_at = datetime.now(UTC)
        async with self._uow_factory() as uow:
            return await uow.task_repo.try_heartbeat_kb_ingestion_task(
                task_id=self._task_id,
                expected_attempt=self._expected_attempt,
                heartbeat_at=heartbeat_at,
                lease_expires_at=heartbeat_at + timedelta(seconds=self._lease_seconds),
            )

    def _log_context(self, event: str) -> dict[str, object]:
        return {
            "event": event,
            "task_id": str(self._task_id),
            "attempt": self._expected_attempt,
        }
