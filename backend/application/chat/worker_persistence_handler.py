"""Worker-side chat message persistence.

职责：在 worker 生成完成或失败后回写助手消息、记录 token 消耗并维护幂等锁。
边界：本模块不执行 RAG 检索、不调用 LLM，也不发布流式 chunk / done 事件。
"""

import logging
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import AppException
from backend.infra.redis import RedisClient
from backend.models.enums import ChatGenerationStatus
from backend.models.schemas.chat.payloads import GenerationAttemptPayload
from backend.services.chat_safety_metadata import ResponseOutcome, build_safety_metadata
from backend.services.chat_service import ChatMessageUpdater
from backend.services.credit_service import CreditService

logger = logging.getLogger(__name__)


class GenerationAttemptRejected(RuntimeError):
    """Raised when a stale Worker cannot mutate the current request attempt."""


class TerminalSettlementError(RuntimeError):
    """Raised after a billing failure was atomically persisted as terminal."""

    def __init__(self, *, error_code: str, error_message: str) -> None:
        self.error_code = error_code
        self.error_message = error_message
        super().__init__(error_message)


class WorkerPersistenceHandler:
    """Persist worker generation outcomes."""

    def __init__(
        self,
        *,
        uow: AbstractUnitOfWork,
        redis_client: RedisClient,
    ) -> None:
        self.uow = uow
        self._redis_client = redis_client

    async def _redis(self) -> redis.Redis:
        return await self._redis_client.init()

    async def write_idempotency_message(
        self,
        *,
        idempotency_lock_key: str,
        assistant_message_id: uuid.UUID,
    ) -> bool:
        try:
            redis_connection = await self._redis()
            await redis_connection.set(
                idempotency_lock_key,
                str(assistant_message_id),
                ex=3600,
            )
        except Exception:
            logger.warning(
                "Chat terminal Redis marker write failed: message_id=%s",
                assistant_message_id,
                exc_info=True,
            )
            return False
        return True

    async def _finalize_request(
        self,
        *,
        generation_attempt: GenerationAttemptPayload | None,
        target_status: ChatGenerationStatus,
        assistant_message_id: uuid.UUID,
        retryable: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if generation_attempt is None:
            return
        finalized = await self.uow.chat_repo.try_finalize_generation_request(
            request_id=generation_attempt.request_id,
            expected_attempt=generation_attempt.attempt,
            lease_token=generation_attempt.lease_token,
            target_status=target_status,
            finished_at=datetime.now(UTC),
            assistant_message_id=assistant_message_id,
            retryable=retryable,
            error_code=error_code,
            error_message=error_message,
        )
        if not finalized:
            raise GenerationAttemptRejected(
                "generation request attempt is no longer current"
            )

    async def persist_success(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        content: str,
        tokens_input: int | None,
        tokens_output: int,
        search_context: dict | None,
        start_time: float,
        message_metadata: dict | None = None,
        model_name: str = "default",
        generation_attempt: GenerationAttemptPayload | None = None,
    ) -> None:
        if assistant_message_id is None:
            return

        billing_error: AppException | None = None
        billing_error_content = (
            "Credits 余额不足，本次生成未记录。已生成的内容不会被扣费，请签到后再试。"
        )
        async with self.uow:
            updater = ChatMessageUpdater(self.uow)

            if user_id is not None and tokens_input is not None:
                credit_service = CreditService(self.uow)
                try:
                    async with self.uow.savepoint():
                        await credit_service.spend_for_model_usage(
                            user_id=user_id,
                            tokens_input=tokens_input,
                            tokens_output=tokens_output,
                            model_name=model_name,
                            chat_message_id=assistant_message_id,
                        )
                except AppException as exc:
                    billing_error = exc
                    logger.warning(
                        "Credits settlement rejected: user_id=%s, input=%d, output=%d, code=%s",
                        user_id,
                        tokens_input,
                        tokens_output,
                        exc.code,
                    )

            if billing_error is not None:
                await updater.update_as_failed(
                    message_id=assistant_message_id,
                    error_content=billing_error_content,
                    message_metadata=build_safety_metadata(
                        response_outcome=ResponseOutcome.FAILED,
                    ),
                )
                await self._finalize_request(
                    generation_attempt=generation_attempt,
                    target_status=ChatGenerationStatus.FAILED,
                    assistant_message_id=assistant_message_id,
                    retryable=True,
                    error_code=billing_error.code,
                    error_message=billing_error_content,
                )
            else:
                await updater.update_as_success(
                    message_id=assistant_message_id,
                    content=content,
                    start_time=start_time,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    search_context=search_context,
                    message_metadata=message_metadata,
                )
                await self._finalize_request(
                    generation_attempt=generation_attempt,
                    target_status=ChatGenerationStatus.SUCCEEDED,
                    assistant_message_id=assistant_message_id,
                )

        if billing_error is not None:
            raise TerminalSettlementError(
                error_code=billing_error.code,
                error_message=billing_error_content,
            )

    async def persist_failure(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        error_content: str,
        idempotency_lock_key: str | None,
        generation_attempt: GenerationAttemptPayload | None = None,
        error_code: str = "CHAT_GENERATION_FAILED",
        retryable: bool = True,
    ) -> None:
        if assistant_message_id is not None:
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_failed(
                    message_id=assistant_message_id,
                    error_content=error_content,
                    message_metadata=build_safety_metadata(
                        response_outcome=ResponseOutcome.FAILED,
                    ),
                )
                await self._finalize_request(
                    generation_attempt=generation_attempt,
                    target_status=ChatGenerationStatus.FAILED,
                    assistant_message_id=assistant_message_id,
                    retryable=retryable,
                    error_code=error_code,
                    error_message=error_content,
                )

        if idempotency_lock_key is not None:
            try:
                redis_connection = await self._redis()
                await redis_connection.delete(idempotency_lock_key)
            except Exception:
                logger.warning(
                    "Chat terminal Redis lock cleanup failed: key=%s",
                    idempotency_lock_key,
                    exc_info=True,
                )
