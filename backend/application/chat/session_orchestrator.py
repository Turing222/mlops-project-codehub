"""Shared web chat request preparation.

职责：复用 Web 流式和非流式聊天的幂等、会话、消息和 payload 准备流程。
边界：本模块不序列化 HTTP/SSE 响应，也不消费 Worker 流式结果。
失败处理：准备阶段失败由调用方按 stream/non-stream 协议转换响应。
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import redis.asyncio as redis
from sqlalchemy.exc import IntegrityError

from backend.application.chat.history_projection import history_to_conversation_messages
from backend.config.credit_settings import credit_settings
from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.concurrency import db_concurrency_slot
from backend.core.exceptions import (
    AppException,
    app_bad_request,
    app_not_found,
    app_service_error,
)
from backend.infra.redis import safe_release_lock
from backend.models.enums import ChatGenerationStatus
from backend.models.schemas.chat.commands import (
    ChatQueryCommand,
    RetryChatGenerationCommand,
)
from backend.models.schemas.chat.payloads import (
    GENERATION_REQUEST_CONTEXT_KEY,
    FeatureFlags,
    GenerationAttemptPayload,
    GenerationPayload,
    GenerationRequestContext,
)
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.chat_service import SessionManager
from backend.services.credit_service import CreditService
from backend.services.feature_flag_service import FeatureFlagService
from backend.services.permission_service import PermissionService
from backend.utils.token_estimation import estimate_messages_tokens, estimate_tokens

if TYPE_CHECKING:
    from backend.models.orm.chat import (
        ChatGenerationRequest,
        ChatMessage,
        ChatSession,
    )


@dataclass(frozen=True, slots=True)
class ChatIdempotencyState:
    """一次聊天请求的幂等锁状态。"""

    lock_key: str | None
    lock_token: str | None
    is_new: bool
    value: str | None

    @property
    def is_processing_duplicate(self) -> bool:
        return self.value is not None and self.value.startswith("processing:")


@dataclass(slots=True)
class ChatPreparedRequest:
    """Web workflow 投递 Worker 前所需的共享上下文。"""

    session: ChatSession
    generation_request: ChatGenerationRequest
    assistant_message: ChatMessage
    generation_payload: GenerationPayload
    lock_key: str | None
    lock_token: str | None
    trace_attrs: dict[str, object]


class ChatSessionOrchestrator:
    """准备 Web 聊天请求的共享编排器。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        redis_client: redis.Redis,
        permission_service: PermissionService,
        feature_flag_service: FeatureFlagService,
        session_manager: SessionManager | None = None,
    ) -> None:
        self.uow = uow
        self.redis = redis_client
        self.permission_service = permission_service
        self._feature_flag_service = feature_flag_service
        self._session_manager = session_manager or SessionManager(
            uow, permission_service
        )

    async def resolve_existing_generation_request(
        self,
        *,
        command: ChatQueryCommand,
    ) -> ChatGenerationRequest | None:
        """Resolve accepted identity from PostgreSQL before consulting Redis."""
        if command.client_request_id is None:
            return None
        async with self.uow.read_context():
            return await self.uow.chat_repo.get_generation_request_by_client_request_id_for_actor(
                user_id=command.user_id,
                client_request_id=command.client_request_id,
            )

    async def prepare_retry_request(
        self,
        *,
        command: RetryChatGenerationCommand,
        trace_attrs: dict[str, object],
    ) -> ChatPreparedRequest:
        """CAS one retryable failure and rebuild its original Worker payload."""
        async with db_concurrency_slot(trace_attrs):  # noqa: SIM117
            async with self.uow:
                generation_request = (
                    await self.uow.chat_repo.get_generation_request_for_actor(
                        request_id=command.generation_request_id,
                        user_id=command.user_id,
                    )
                )
                if generation_request is None:
                    raise app_not_found(
                        "生成请求不存在",
                        code="CHAT_GENERATION_REQUEST_NOT_FOUND",
                        details={
                            "generation_request_id": str(command.generation_request_id)
                        },
                    )
                _validate_retry_state(
                    generation_request,
                    expected_attempt=command.expected_attempt,
                )
                if (
                    generation_request.user_message_id is None
                    or generation_request.assistant_message_id is None
                ):
                    raise _retry_conflict(
                        generation_request,
                        code="CHAT_RETRY_CONTEXT_UNAVAILABLE",
                        message="原请求上下文不完整，无法安全重试",
                    )

                user_message = await self.uow.chat_repo.get_message(
                    generation_request.user_message_id
                )
                assistant_message = await self.uow.chat_repo.get_message(
                    generation_request.assistant_message_id
                )
                if (
                    user_message is None
                    or assistant_message is None
                    or user_message.role != "user"
                    or assistant_message.role != "assistant"
                ):
                    raise _retry_conflict(
                        generation_request,
                        code="CHAT_RETRY_CONTEXT_UNAVAILABLE",
                        message="原请求消息不存在，无法安全重试",
                    )

                metadata = getattr(user_message, "message_metadata", None) or {}
                try:
                    request_context = GenerationRequestContext.model_validate(
                        metadata[GENERATION_REQUEST_CONTEXT_KEY]
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise _retry_conflict(
                        generation_request,
                        code="CHAT_RETRY_CONTEXT_UNAVAILABLE",
                        message="原请求缺少安全重试上下文",
                    ) from exc

                await CreditService(self.uow).ensure_sufficient_balance(
                    command.user_id,
                    estimated_cost=max(
                        generation_request.reserved_credits,
                        credit_settings.CREDIT_MINIMUM_ESTIMATED_COST,
                    ),
                )
                session = await self._session_manager.ensure_session(
                    user_id=command.user_id,
                    query_text=user_message.content,
                    session_id=generation_request.session_id,
                )
                history_messages = await self.uow.chat_repo.get_session_messages(
                    session_id=session.id,
                    limit=settings.CHAT_MEMORY_FETCH_LIMIT,
                )
                context_state = await self.uow.chat_repo.get_context_state(session.id)
                retry_started_at = datetime.now(UTC)
                next_attempt = await self.uow.chat_repo.try_retry_generation_request(
                    request_id=generation_request.id,
                    user_id=command.user_id,
                    expected_attempt=command.expected_attempt,
                    recovery_due_at=retry_started_at
                    + timedelta(
                        seconds=settings.CHAT_GENERATION_QUEUE_RECOVERY_SECONDS
                    ),
                )
                if next_attempt is None:
                    raise _retry_conflict(
                        generation_request,
                        code="CHAT_RETRY_ATTEMPT_CONFLICT",
                        message="请求状态已变化，请刷新后重试",
                    )
                reset = await self.uow.chat_repo.reset_assistant_message_for_retry(
                    message_id=assistant_message.id
                )
                if not reset:
                    raise _retry_conflict(
                        generation_request,
                        code="CHAT_RETRY_MESSAGE_CONFLICT",
                        message="失败消息状态已变化，请刷新后重试",
                    )

        generation_request.attempt = next_attempt
        generation_request.status = ChatGenerationStatus.PREPARED
        generation_request.retryable = False
        trace_attrs.update(
            {
                "chat.session_id": session.id,
                "chat.generation_request_id": generation_request.id,
                "chat.assistant_message_id": assistant_message.id,
                "chat.generation_attempt": next_attempt,
            }
        )
        conversation_history = history_to_conversation_messages(
            [
                message
                for message in history_messages
                if message.id != assistant_message.id
            ]
        )
        generation_payload = GenerationPayload(
            session_id=session.id,
            query_text=user_message.content,
            conversation_history=conversation_history,
            kb_id=session.kb_id,
            context_state=context_state,
            enable_external_context=request_context.enable_external_context,
            context_mode=request_context.context_mode,
            billing_model_name=request_context.billing_model_name,
            extra_body=request_context.extra_body,
            feature_flags=await _resolve_generation_feature_flags(
                self._feature_flag_service
            ),
        )
        return ChatPreparedRequest(
            session=session,
            generation_request=generation_request,
            assistant_message=assistant_message,
            generation_payload=generation_payload,
            lock_key=None,
            lock_token=None,
            trace_attrs=trace_attrs,
        )

    async def check_idempotency(
        self,
        *,
        command: ChatQueryCommand,
        trace_attrs: dict[str, object],
        span_name: str,
    ) -> ChatIdempotencyState:
        lock_key: str | None = None
        lock_token: str | None = None
        value: str | None = None
        is_new = True

        with trace_span(span_name, trace_attrs) as span:
            if command.client_request_id:
                lock_key = (
                    f"idempotency:chat:{command.user_id}:{command.client_request_id}"
                )
                lock_token = f"processing:{uuid.uuid4()}"
                is_new = bool(
                    await self.redis.set(lock_key, lock_token, nx=True, ex=300)
                )
                set_span_attributes(span, {"chat.idempotency.is_new": is_new})
                if not is_new:
                    value = await self.redis.get(lock_key)
                    set_span_attributes(span, {"chat.idempotency.value": value})

        return ChatIdempotencyState(
            lock_key=lock_key,
            lock_token=lock_token,
            is_new=is_new,
            value=value,
        )

    async def prepare_request(
        self,
        *,
        command: ChatQueryCommand,
        idempotency: ChatIdempotencyState,
        trace_attrs: dict[str, object],
        span_prefix: str,
    ) -> ChatPreparedRequest:
        try:
            return await self._prepare_request_inner(
                command=command,
                idempotency=idempotency,
                trace_attrs=trace_attrs,
                span_prefix=span_prefix,
            )
        except AppException:
            await self.release_idempotency(idempotency)
            raise
        except IntegrityError as exc:
            await self.release_idempotency(idempotency)
            raise app_service_error(
                "该请求已被接受，请刷新页面查看状态",
                code="CHAT_REQUEST_ALREADY_EXISTS",
                details={"client_request_id": command.client_request_id},
            ) from exc
        except Exception:
            await self.release_idempotency(idempotency)
            raise

    async def _prepare_request_inner(
        self,
        *,
        command: ChatQueryCommand,
        idempotency: ChatIdempotencyState,
        trace_attrs: dict[str, object],
        span_prefix: str,
    ) -> ChatPreparedRequest:
        async with db_concurrency_slot(trace_attrs):  # noqa: SIM117
            async with self.uow:
                # Credit pre-check BEFORE session/message creation to avoid
                # lock-order inversion with the worker path (User→CreditAccount→chat).
                with trace_span(f"{span_prefix}.credit_precheck", trace_attrs) as span:
                    billing_model_name = _resolve_billing_model_name()
                    estimated_cost = _estimate_credit_cost(
                        query_text=command.query_text,
                        conversation_history=[],
                        model_name=billing_model_name,
                    )
                    set_span_attributes(
                        span,
                        {
                            "credit.estimated_cost": estimated_cost,
                            "credit.model_name": billing_model_name,
                        },
                    )
                    await CreditService(self.uow).ensure_sufficient_balance(
                        command.user_id, estimated_cost=estimated_cost
                    )

                with trace_span(
                    f"{span_prefix}.prepare_chat_context",
                    trace_attrs,
                ) as span:
                    session_manager = self._session_manager
                    resolved_kb_id = command.kb_id

                    session = await session_manager.ensure_session(
                        user_id=command.user_id,
                        query_text=command.query_text,
                        session_id=command.session_id,
                        kb_id=resolved_kb_id,
                    )
                    # 已有会话：session.kb_id 不可覆盖；新会话：使用经权限校验的 resolved_kb_id。
                    if command.session_id is not None:
                        if command.kb_id is not None and command.kb_id != session.kb_id:
                            raise app_bad_request(
                                "请求的知识库与会话绑定的知识库不一致",
                                code="KB_ID_MISMATCH",
                                details={
                                    "request_kb_id": str(command.kb_id),
                                    "session_kb_id": str(session.kb_id),
                                },
                            )
                        effective_kb_id = session.kb_id
                    else:
                        effective_kb_id = resolved_kb_id or session.kb_id
                    request_context = GenerationRequestContext(
                        enable_external_context=command.enable_external_context,
                        context_mode=command.context_mode,
                        billing_model_name=billing_model_name,
                        extra_body=command.extra_body,
                    )
                    user_message = await session_manager.create_user_message(
                        session_id=session.id,
                        content=command.query_text,
                        user_id=command.user_id,
                        message_metadata={
                            GENERATION_REQUEST_CONTEXT_KEY: request_context.model_dump(
                                mode="json"
                            )
                        },
                    )
                    assistant_message = await session_manager.create_assistant_message(
                        session_id=session.id,
                        user_id=command.user_id,
                    )
                    durable_client_request_id = command.client_request_id or (
                        f"server-{uuid.uuid4().hex}"
                    )
                    prepared_at = datetime.now(UTC)
                    generation_request = (
                        await self.uow.chat_repo.create_generation_request(
                            user_id=command.user_id,
                            workspace_id=session.workspace_id,
                            session_id=session.id,
                            user_message_id=user_message.id,
                            assistant_message_id=assistant_message.id,
                            client_request_id=durable_client_request_id,
                            recovery_due_at=prepared_at
                            + timedelta(
                                seconds=settings.CHAT_GENERATION_QUEUE_RECOVERY_SECONDS
                            ),
                            reserved_credits=estimated_cost,
                        )
                    )

                    history_messages = await session_manager.get_session_messages(
                        session_id=session.id,
                        limit=settings.CHAT_MEMORY_FETCH_LIMIT,
                    )
                    context_state = await self.uow.chat_repo.get_context_state(
                        session.id
                    )

                    set_span_attributes(
                        span,
                        {
                            "chat.session_id": session.id,
                            "chat.generation_request_id": generation_request.id,
                            "chat.assistant_message_id": assistant_message.id,
                            "chat.history.message_count": len(history_messages),
                            "chat.context_state.present": context_state is not None,
                        },
                    )
                trace_attrs["chat.session_id"] = session.id
                trace_attrs["chat.generation_request_id"] = generation_request.id
                trace_attrs["chat.assistant_message_id"] = assistant_message.id

        conversation_history = history_to_conversation_messages(history_messages)

        with trace_span(f"{span_prefix}.prepare_worker_payload", trace_attrs) as span:
            set_span_attributes(
                span,
                {
                    "chat.history.message_count": len(conversation_history),
                    "rag.deferred_to_worker": effective_kb_id is not None,
                    "external_context.enabled": command.enable_external_context,
                    "context.mode": command.context_mode,
                },
            )

        generation_payload = GenerationPayload(
            session_id=session.id,
            query_text=command.query_text,
            conversation_history=conversation_history,
            kb_id=effective_kb_id,
            context_state=context_state,
            enable_external_context=command.enable_external_context,
            context_mode=command.context_mode,
            billing_model_name=billing_model_name,
            extra_body=command.extra_body,
        )

        generation_payload.feature_flags = await _resolve_generation_feature_flags(
            self._feature_flag_service
        )
        return ChatPreparedRequest(
            session=session,
            generation_request=generation_request,
            assistant_message=assistant_message,
            generation_payload=generation_payload,
            lock_key=idempotency.lock_key,
            lock_token=idempotency.lock_token,
            trace_attrs=trace_attrs,
        )

    async def queue_generation_request(
        self,
        *,
        prepared: ChatPreparedRequest,
        user_id: uuid.UUID,
        task_id: str,
    ) -> GenerationAttemptPayload:
        """Fence one committed PREPARED request before broker dispatch."""
        queued_at = datetime.now(UTC)
        attempt = GenerationAttemptPayload(
            request_id=prepared.generation_request.id,
            attempt=prepared.generation_request.attempt,
            task_id=task_id,
            lease_token=uuid.uuid4().hex,
        )
        async with db_concurrency_slot(prepared.trace_attrs), self.uow:
            queued = await self.uow.chat_repo.try_queue_generation_request(
                request_id=attempt.request_id,
                user_id=user_id,
                expected_attempt=attempt.attempt,
                task_id=attempt.task_id,
                lease_token=attempt.lease_token,
                queued_at=queued_at,
                recovery_due_at=queued_at
                + timedelta(seconds=settings.CHAT_GENERATION_QUEUE_RECOVERY_SECONDS),
            )
        if not queued:
            raise app_service_error(
                "请求状态已变化，请刷新页面后重试",
                code="CHAT_REQUEST_STATE_CONFLICT",
                details={"generation_request_id": str(attempt.request_id)},
            )
        return attempt

    async def release_idempotency(self, idempotency: ChatIdempotencyState) -> None:
        if idempotency.lock_key is None or idempotency.lock_token is None:
            return
        await safe_release_lock(
            self.redis,
            idempotency.lock_key,
            idempotency.lock_token,
        )


def _retry_conflict(
    generation_request: ChatGenerationRequest,
    *,
    code: str,
    message: str,
) -> AppException:
    return AppException(
        code=code,
        message=message,
        status_code=409,
        details={
            "generation_request_id": str(generation_request.id),
            "attempt": generation_request.attempt,
            "status": str(generation_request.status),
        },
    )


def _validate_retry_state(
    generation_request: ChatGenerationRequest,
    *,
    expected_attempt: int,
) -> None:
    status = ChatGenerationStatus(generation_request.status)
    if generation_request.attempt != expected_attempt:
        raise _retry_conflict(
            generation_request,
            code="CHAT_RETRY_ATTEMPT_CONFLICT",
            message="重试版本已变化，请刷新后重试",
        )
    if status in {
        ChatGenerationStatus.PREPARED,
        ChatGenerationStatus.QUEUED,
        ChatGenerationStatus.RUNNING,
    }:
        raise _retry_conflict(
            generation_request,
            code="CHAT_REQUEST_STILL_RUNNING",
            message="请求仍在生成中，请稍后刷新",
        )
    if status == ChatGenerationStatus.SUCCEEDED:
        raise _retry_conflict(
            generation_request,
            code="CHAT_REQUEST_ALREADY_SUCCEEDED",
            message="请求已经成功完成，无需重试",
        )
    if not generation_request.retryable:
        raise _retry_conflict(
            generation_request,
            code="CHAT_REQUEST_NOT_RETRYABLE",
            message="该失败不支持重试",
        )


async def _resolve_generation_feature_flags(
    feature_flag_service: FeatureFlagService,
) -> FeatureFlags:
    system_flags = await feature_flag_service.get_system_features()
    return FeatureFlags(
        enable_external_context=system_flags.get("enable-external-context", False),
        enable_rag_rerank=system_flags.get("enable-rag-rerank", False),
        enable_rag_planner=system_flags.get("enable-rag-planner", False),
        enable_rag_planner_routing=system_flags.get(
            "enable-rag-planner-routing", False
        ),
        enable_rag_refusal=system_flags.get("enable-rag-refusal", True),
        enable_llm_model_routing=system_flags.get("enable-llm-model-routing", False),
        enable_rag_planner_thinking=system_flags.get(
            "enable-rag-planner-thinking", False
        ),
    )


def _resolve_billing_model_name() -> str:
    """Resolve the model name used for credit billing (first candidate)."""
    try:
        config = get_llm_model_config()
        profiles = config.resolve_route(settings.LLM_PROVIDER)
        return profiles[0].model
    except Exception:
        return "default"


def _estimate_credit_cost(
    *,
    query_text: str,
    conversation_history: list[dict],
    model_name: str,
) -> int:
    """Estimate credit cost based on input tokens + estimated output tokens."""
    input_tokens = estimate_tokens(query_text, model_name)
    if conversation_history:
        input_tokens += estimate_messages_tokens(conversation_history, model_name)

    output_tokens = credit_settings.CREDIT_ESTIMATED_OUTPUT_TOKENS
    rates = credit_settings.CREDIT_MODEL_RATES.get(
        model_name
    ) or credit_settings.CREDIT_MODEL_RATES.get("default", {})
    input_rate = rates.get("input", 1.0)
    output_rate = rates.get("output", 1.0)

    raw_cost = (input_tokens * input_rate + output_tokens * output_rate) / 1000.0
    return max(math.ceil(raw_cost), credit_settings.CREDIT_MINIMUM_ESTIMATED_COST)
