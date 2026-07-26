"""Worker-side lease heartbeat for durable Chat generation attempts.

职责：使用独立 UoW 周期续租当前 RUNNING attempt，并在 fence 失效后停止续租。
边界：不改变业务 attempt、不提交终态；最终写入仍由 Worker persistence CAS 保护。
副作用：周期更新 PostgreSQL heartbeat_at、lease_expires_at 与 recovery_due_at。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.models.schemas.chat.payloads import GenerationAttemptPayload

logger = logging.getLogger(__name__)


class GenerationLeaseHeartbeat:
    """Renew one current attempt without sharing the generation transaction."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork] | None,
        generation_attempt: GenerationAttemptPayload | None,
        interval_seconds: float | None = None,
        lease_seconds: int | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._generation_attempt = generation_attempt
        self._interval_seconds = interval_seconds or (
            ai_settings.CHAT_GENERATION_HEARTBEAT_SECONDS
        )
        self._lease_seconds = lease_seconds or ai_settings.CHAT_GENERATION_LEASE_SECONDS
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.lease_lost = False

    async def start(self) -> bool:
        """Renew immediately, then start periodic renewal when configured."""
        if self._uow_factory is None or self._generation_attempt is None:
            return True
        if not await self._renew():
            self.lease_lost = True
            return False
        self._task = asyncio.create_task(
            self._run(),
            name=f"chat-heartbeat-{self._generation_attempt.request_id}",
        )
        return True

    async def stop(self) -> None:
        """Stop periodic renewal without masking the generation outcome."""
        self._stop_event.set()
        if self._task is None:
            return
        try:
            await self._task
        except Exception:
            logger.warning(
                "Chat generation heartbeat task failed during shutdown",
                exc_info=True,
            )
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set() and not self.lease_lost:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )
            if self._stop_event.is_set():
                return
            try:
                renewed = await self._renew()
            except Exception:
                logger.warning(
                    "Chat generation heartbeat write failed",
                    extra=self._log_context("chat_generation_heartbeat_error"),
                    exc_info=True,
                )
                continue
            if not renewed:
                self.lease_lost = True
                logger.warning(
                    "Chat generation heartbeat fence rejected",
                    extra=self._log_context("chat_generation_heartbeat_rejected"),
                )

    async def _renew(self) -> bool:
        if self._uow_factory is None or self._generation_attempt is None:
            return True
        heartbeat_at = datetime.now(UTC)
        async with self._uow_factory() as uow:
            return await uow.chat_repo.try_heartbeat_generation_request(
                request_id=self._generation_attempt.request_id,
                expected_attempt=self._generation_attempt.attempt,
                lease_token=self._generation_attempt.lease_token,
                heartbeat_at=heartbeat_at,
                lease_expires_at=heartbeat_at + timedelta(seconds=self._lease_seconds),
            )

    def _log_context(self, event: str) -> dict[str, object]:
        attempt = self._generation_attempt
        return {
            "event": event,
            "generation_request_id": str(attempt.request_id) if attempt else None,
            "attempt": attempt.attempt if attempt else None,
            "task_id": attempt.task_id if attempt else None,
        }
