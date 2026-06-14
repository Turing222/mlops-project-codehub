"""Worker-side guardrail rejection handler.

职责：处理输入护栏拦截和 RAG 拒答后的持久化、Redis 发布和结果返回。
边界：本模块不做 LLM 编排或 RAG 检索；流式路径通过 stream_publisher 发布到 Redis。
"""

import logging
import uuid
from collections.abc import Callable

from backend.application.chat.worker_persistence_handler import WorkerPersistenceHandler
from backend.application.chat.worker_stream_publisher import WorkerStreamPublisher
from backend.config.ai_settings import ai_settings
from backend.models.schemas.chat.payloads import GenerationResult
from backend.services.chat_safety_metadata import (
    INJECTION_REFUSAL_MESSAGE,
    SAFETY_REFUSAL_MESSAGE,
    GuardrailDecision,
    GuardrailReason,
    ResponseOutcome,
    build_planner_refusal_metadata,
    build_rag_refusal_metadata,
    build_safety_metadata,
)

logger = logging.getLogger(__name__)


class WorkerGuardrailHandler:
    """Handle guardrail rejection and RAG refusal persistence."""

    def __init__(
        self,
        *,
        persistence_handler: WorkerPersistenceHandler,
        stream_publisher: WorkerStreamPublisher | None = None,
        count_output_tokens: Callable[[str], int],
    ) -> None:
        self._persistence_handler = persistence_handler
        self._stream_publisher = stream_publisher
        self._count_output_tokens = count_output_tokens

    # ── Stream Handlers ───────────────────────────────────────────

    async def handle_stream_input_block(
        self,
        *,
        channel: str,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        input_decision: GuardrailDecision,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> None:
        refusal_message = (
            INJECTION_REFUSAL_MESSAGE
            if input_decision.reason == GuardrailReason.INJECTION_RISK.value
            else SAFETY_REFUSAL_MESSAGE
        )
        tokens_output = self._count_output_tokens(refusal_message)
        if self._stream_publisher is not None:
            await self._stream_publisher.publish_chunk(channel, refusal_message)
        await self._persist_refusal(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=refusal_message,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=None,
            start_time=start_time,
            message_metadata=build_safety_metadata(
                response_outcome=ResponseOutcome.BLOCKED,
                input_decision=input_decision,
            ),
            idempotency_lock_key=idempotency_lock_key,
        )

    async def handle_stream_refusal(
        self,
        *,
        channel: str,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search_context: dict | None,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> None:
        planner_refusal = bool(search_context and search_context.get("planner_refusal"))
        refusal_content = (
            ai_settings.RAG_PLANNER_REFUSAL_MESSAGE
            if planner_refusal
            else ai_settings.RAG_REFUSAL_MESSAGE
        )
        tokens_output = self._count_output_tokens(refusal_content)
        if self._stream_publisher is not None:
            await self._stream_publisher.publish_chunk(channel, refusal_content)
        await self._persist_refusal(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=refusal_content,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=(
                build_planner_refusal_metadata()
                if planner_refusal
                else build_rag_refusal_metadata()
            ),
            idempotency_lock_key=idempotency_lock_key,
        )

    # ── Non-Stream Handlers ───────────────────────────────────────

    async def handle_nonstream_input_block(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        input_decision: GuardrailDecision,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> GenerationResult:
        refusal_message = (
            INJECTION_REFUSAL_MESSAGE
            if input_decision.reason == GuardrailReason.INJECTION_RISK.value
            else SAFETY_REFUSAL_MESSAGE
        )
        tokens_output = self._count_output_tokens(refusal_message)
        await self._persist_refusal(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=refusal_message,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=None,
            start_time=start_time,
            message_metadata=build_safety_metadata(
                response_outcome=ResponseOutcome.BLOCKED,
                input_decision=input_decision,
            ),
            idempotency_lock_key=idempotency_lock_key,
        )
        return GenerationResult(
            success=True,
            content=refusal_message,
            tokens_input=0,
            tokens_output=tokens_output,
        )

    async def handle_nonstream_refusal(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search_context: dict | None,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> GenerationResult:
        planner_refusal = bool(search_context and search_context.get("planner_refusal"))
        refusal_content = (
            ai_settings.RAG_PLANNER_REFUSAL_MESSAGE
            if planner_refusal
            else ai_settings.RAG_REFUSAL_MESSAGE
        )
        tokens_output = self._count_output_tokens(refusal_content)
        await self._persist_refusal(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=refusal_content,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=(
                build_planner_refusal_metadata()
                if planner_refusal
                else build_rag_refusal_metadata()
            ),
            idempotency_lock_key=idempotency_lock_key,
        )
        return GenerationResult(
            success=True,
            content=refusal_content,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=search_context,
        )

    # ── Internal ─────────────────────────────────────────────────

    async def _persist_refusal(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        content: str,
        tokens_input: int,
        tokens_output: int,
        search_context: dict | None,
        start_time: float,
        message_metadata: dict[str, object],
        idempotency_lock_key: str | None,
    ) -> None:
        await self._persistence_handler.persist_success(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=content,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=message_metadata,
            model_name="default",
        )
        if idempotency_lock_key is not None and assistant_message_id is not None:
            await self._persistence_handler.write_idempotency_message(
                idempotency_lock_key=idempotency_lock_key,
                assistant_message_id=assistant_message_id,
            )
