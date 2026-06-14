"""Worker-side chat message persistence.

职责：在 worker 生成完成或失败后回写助手消息、记录 token 消耗并维护幂等锁。
边界：本模块不执行 RAG 检索、不调用 LLM，也不发布流式 chunk / done 事件。
"""

import logging
import uuid

import redis.asyncio as redis

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import AppException
from backend.infra.redis import RedisClient
from backend.services.chat_safety_metadata import ResponseOutcome, build_safety_metadata
from backend.services.chat_service import ChatMessageUpdater
from backend.services.credit_service import CreditService

logger = logging.getLogger(__name__)


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
    ) -> None:
        redis_connection = await self._redis()
        await redis_connection.set(
            idempotency_lock_key,
            str(assistant_message_id),
            ex=3600,
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
    ) -> None:
        if assistant_message_id is None:
            return

        async with self.uow:
            updater = ChatMessageUpdater(self.uow)

            # Phase 1: Atomic credits billing.
            if user_id is not None and tokens_input is not None:
                credit_service = CreditService(self.uow)
                try:
                    await credit_service.spend_for_model_usage(
                        user_id=user_id,
                        tokens_input=tokens_input,
                        tokens_output=tokens_output,
                        model_name=model_name,
                        chat_message_id=assistant_message_id,
                    )
                except AppException as exc:
                    logger.warning(
                        "Credits 扣减失败，回写失败状态: user_id=%s, input=%d, output=%d, error=%s",
                        user_id,
                        tokens_input,
                        tokens_output,
                        str(exc),
                    )
                    await updater.update_as_failed(
                        message_id=assistant_message_id,
                        error_content="Credits 余额不足，本次生成未记录。已生成的内容不会被扣费，请签到后再试。",
                        message_metadata=build_safety_metadata(
                            response_outcome=ResponseOutcome.FAILED,
                        ),
                    )
                    return

            # Phase 2: Mark as SUCCESS (billing confirmed or not applicable).
            await updater.update_as_success(
                message_id=assistant_message_id,
                content=content,
                start_time=start_time,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                search_context=search_context,
                message_metadata=message_metadata,
            )

    async def persist_failure(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        error_content: str,
        idempotency_lock_key: str | None,
    ) -> None:
        if idempotency_lock_key is not None:
            try:
                redis_connection = await self._redis()
                await redis_connection.delete(idempotency_lock_key)
            except Exception:
                logger.debug(
                    "Worker 清理幂等锁失败: key=%s",
                    idempotency_lock_key,
                    exc_info=True,
                )

        if assistant_message_id is None:
            return

        try:
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_failed(
                    message_id=assistant_message_id,
                    error_content=error_content,
                    message_metadata=build_safety_metadata(
                        response_outcome=ResponseOutcome.FAILED,
                    ),
                )
        except Exception:
            logger.exception(
                "Worker 回写助手消息失败状态异常: message_id=%s",
                assistant_message_id,
            )
