"""Durable Chat generation recovery orchestration.

职责：扫描到期 generation request，以 CAS 有界补派发或写入可重试失败终态。
边界：只经 AbstractTaskDispatcher 投递；不自动重放已经进入 RUNNING 的 LLM attempt。
副作用：更新 PostgreSQL request/message 状态，并向 task broker 发送恢复消息。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractTaskDispatcher, AbstractUnitOfWork
from backend.models.enums import ChatGenerationStatus
from backend.models.orm.chat import ChatGenerationRequest
from backend.models.schemas.chat.payloads import (
    GenerationAttemptPayload,
    GenerationDispatchContext,
)
from backend.observability.trace_utils import inject_trace_context
from backend.services.chat_safety_metadata import ResponseOutcome, build_safety_metadata
from backend.services.chat_service import ChatMessageUpdater

logger = logging.getLogger(__name__)

DISPATCH_EXHAUSTED_CODE = "CHAT_DISPATCH_RETRY_EXHAUSTED"
LEASE_EXPIRED_CODE = "CHAT_GENERATION_LEASE_EXPIRED"
CONTEXT_UNAVAILABLE_CODE = "CHAT_RECOVERY_CONTEXT_UNAVAILABLE"


@dataclass(slots=True)
class ChatGenerationRecoveryResult:
    """One bounded recovery scan result."""

    scanned_count: int = 0
    prepared_dispatched_count: int = 0
    queued_redispatched_count: int = 0
    failed_count: int = 0
    conflict_count: int = 0
    dispatch_error_count: int = 0


class ChatGenerationRecoveryService:
    """Converge due Chat requests through exact-fence repository operations."""

    def __init__(
        self,
        *,
        uow: AbstractUnitOfWork,
        dispatcher: AbstractTaskDispatcher,
        recovery_seconds: int | None = None,
        max_dispatch_attempts: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.uow = uow
        self.dispatcher = dispatcher
        self.recovery_seconds = recovery_seconds or (
            ai_settings.CHAT_GENERATION_QUEUE_RECOVERY_SECONDS
        )
        self.max_dispatch_attempts = max_dispatch_attempts or (
            ai_settings.CHAT_GENERATION_MAX_DISPATCH_ATTEMPTS
        )
        self.batch_size = batch_size or ai_settings.CHAT_GENERATION_RECOVERY_BATCH_SIZE

    async def reconcile_due_requests(
        self,
        *,
        now: datetime | None = None,
    ) -> ChatGenerationRecoveryResult:
        current_time = now or datetime.now(UTC)
        async with self.uow.read_context():
            due_requests = await self.uow.chat_repo.get_due_generation_requests(
                due_at=current_time,
                limit=self.batch_size,
            )

        result = ChatGenerationRecoveryResult(scanned_count=len(due_requests))
        for generation_request in due_requests:
            await self._reconcile_one(generation_request, current_time, result)
        return result

    async def _reconcile_one(
        self,
        generation_request: ChatGenerationRequest,
        current_time: datetime,
        result: ChatGenerationRecoveryResult,
    ) -> None:
        status = ChatGenerationStatus(generation_request.status)
        if status == ChatGenerationStatus.RUNNING:
            if await self._fail_request(
                generation_request,
                current_time=current_time,
                error_code=LEASE_EXPIRED_CODE,
                error_message="生成任务执行超时，请重试",
            ):
                result.failed_count += 1
            else:
                result.conflict_count += 1
            return

        if generation_request.assistant_message_id is None:
            if await self._fail_request(
                generation_request,
                current_time=current_time,
                error_code=CONTEXT_UNAVAILABLE_CODE,
                error_message="生成任务恢复消息不可用，请重试",
            ):
                result.failed_count += 1
            else:
                result.conflict_count += 1
            return

        try:
            dispatch_context = GenerationDispatchContext.model_validate(
                generation_request.dispatch_context
            )
        except (TypeError, ValidationError):
            if await self._fail_request(
                generation_request,
                current_time=current_time,
                error_code=CONTEXT_UNAVAILABLE_CODE,
                error_message="生成任务恢复上下文不可用，请重试",
            ):
                result.failed_count += 1
            else:
                result.conflict_count += 1
            return

        if status == ChatGenerationStatus.PREPARED:
            await self._recover_prepared(
                generation_request,
                dispatch_context=dispatch_context,
                current_time=current_time,
                result=result,
            )
            return
        if status == ChatGenerationStatus.QUEUED:
            await self._recover_queued(
                generation_request,
                dispatch_context=dispatch_context,
                current_time=current_time,
                result=result,
            )

    async def _recover_prepared(
        self,
        generation_request: ChatGenerationRequest,
        *,
        dispatch_context: GenerationDispatchContext,
        current_time: datetime,
        result: ChatGenerationRecoveryResult,
    ) -> None:
        attempt = GenerationAttemptPayload(
            request_id=generation_request.id,
            attempt=generation_request.attempt,
            task_id=uuid.uuid4().hex,
            lease_token=uuid.uuid4().hex,
        )
        async with self.uow:
            queued = await self.uow.chat_repo.try_queue_generation_request(
                request_id=generation_request.id,
                user_id=generation_request.user_id,
                expected_attempt=generation_request.attempt,
                task_id=attempt.task_id,
                lease_token=attempt.lease_token,
                queued_at=current_time,
                recovery_due_at=self._next_due(current_time),
            )
        if not queued:
            result.conflict_count += 1
            return
        if await self._dispatch(generation_request, dispatch_context, attempt):
            result.prepared_dispatched_count += 1
        else:
            result.dispatch_error_count += 1

    async def _recover_queued(
        self,
        generation_request: ChatGenerationRequest,
        *,
        dispatch_context: GenerationDispatchContext,
        current_time: datetime,
        result: ChatGenerationRecoveryResult,
    ) -> None:
        if generation_request.dispatch_attempts >= self.max_dispatch_attempts:
            if await self._fail_request(
                generation_request,
                current_time=current_time,
                error_code=DISPATCH_EXHAUSTED_CODE,
                error_message="生成任务派发失败，请重试",
            ):
                result.failed_count += 1
            else:
                result.conflict_count += 1
            return
        if not generation_request.task_id or not generation_request.lease_token:
            if await self._fail_request(
                generation_request,
                current_time=current_time,
                error_code=CONTEXT_UNAVAILABLE_CODE,
                error_message="生成任务恢复身份不可用，请重试",
            ):
                result.failed_count += 1
            else:
                result.conflict_count += 1
            return

        attempt = GenerationAttemptPayload(
            request_id=generation_request.id,
            attempt=generation_request.attempt,
            task_id=generation_request.task_id,
            lease_token=generation_request.lease_token,
        )
        async with self.uow:
            reserved = (
                await self.uow.chat_repo.try_reserve_generation_request_redispatch(
                    request_id=generation_request.id,
                    expected_attempt=generation_request.attempt,
                    task_id=attempt.task_id,
                    lease_token=attempt.lease_token,
                    expected_dispatch_attempts=generation_request.dispatch_attempts,
                    max_dispatch_attempts=self.max_dispatch_attempts,
                    due_before=current_time,
                    next_recovery_due_at=self._next_due(current_time),
                )
            )
        if reserved is None:
            result.conflict_count += 1
            return
        if await self._dispatch(generation_request, dispatch_context, attempt):
            result.queued_redispatched_count += 1
        else:
            result.dispatch_error_count += 1

    async def _dispatch(
        self,
        generation_request: ChatGenerationRequest,
        dispatch_context: GenerationDispatchContext,
        attempt: GenerationAttemptPayload,
    ) -> bool:
        try:
            await self.dispatcher.enqueue_generation_recovery(
                dispatch_context=dispatch_context,
                assistant_message_id=str(generation_request.assistant_message_id),
                user_id=str(generation_request.user_id),
                generation_attempt=attempt,
                trace_context=inject_trace_context(),
            )
        except Exception:
            logger.exception(
                "Chat recovery broker dispatch failed",
                extra=self._log_context(
                    generation_request,
                    event="chat_generation_recovery_dispatch_failed",
                ),
            )
            return False
        logger.info(
            "Chat generation redispatched",
            extra=self._log_context(
                generation_request,
                event="chat_generation_redispatched",
            ),
        )
        return True

    async def _fail_request(
        self,
        generation_request: ChatGenerationRequest,
        *,
        current_time: datetime,
        error_code: str,
        error_message: str,
    ) -> bool:
        async with self.uow:
            failed = await self.uow.chat_repo.try_fail_due_generation_request(
                request_id=generation_request.id,
                expected_status=ChatGenerationStatus(generation_request.status),
                expected_attempt=generation_request.attempt,
                expected_dispatch_attempts=generation_request.dispatch_attempts,
                task_id=generation_request.task_id,
                lease_token=generation_request.lease_token,
                due_before=current_time,
                finished_at=current_time,
                error_code=error_code,
                error_message=error_message,
            )
            if not failed:
                return False
            if generation_request.assistant_message_id is not None:
                message = await ChatMessageUpdater(self.uow).update_as_failed(
                    message_id=generation_request.assistant_message_id,
                    error_content=error_message,
                    message_metadata=build_safety_metadata(
                        response_outcome=ResponseOutcome.FAILED,
                    ),
                )
                if message is None:
                    raise RuntimeError("Chat recovery assistant message is missing")
        logger.warning(
            "Chat generation recovery reached terminal failure",
            extra={
                **self._log_context(
                    generation_request,
                    event="chat_generation_recovery_failed",
                ),
                "error_code": error_code,
            },
        )
        return True

    def _next_due(self, current_time: datetime) -> datetime:
        return current_time + timedelta(seconds=self.recovery_seconds)

    @staticmethod
    def _log_context(
        generation_request: ChatGenerationRequest,
        *,
        event: str,
    ) -> dict[str, object]:
        return {
            "event": event,
            "generation_request_id": str(generation_request.id),
            "client_request_id": generation_request.client_request_id,
            "attempt": generation_request.attempt,
            "status": str(generation_request.status),
            "task_id": generation_request.task_id,
            "dispatch_attempts": generation_request.dispatch_attempts,
            "recovery_due_at": generation_request.recovery_due_at,
            "lease_expires_at": generation_request.lease_expires_at,
        }
