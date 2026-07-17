"""LLM TaskIQ tasks.

职责：恢复 trace context、装配 worker 依赖，并调用 worker-side 生成 workflow。
边界：本模块不实现 provider 调用细节，也不直接散写数据库。
"""

import logging
import uuid

from backend.application.chat.worker_generation_workflow import (
    LLMGenerationWorkerWorkflow,
)
from backend.infra.redis import redis_client
from backend.infra.task_broker import broker
from backend.models.schemas.chat.payloads import (
    GenerationAttemptPayload,
    GenerationPayload,
    GenerationResult,
    LLMTaskPayload,
    StreamGenerationResult,
)
from backend.observability.langfuse_utils import (
    langfuse_generation,
    set_langfuse_trace_metadata,
)
from backend.observability.trace_utils import use_trace_context
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.worker.dependencies import (
    get_worker_external_context_provider,
    get_worker_llm_service,
    get_worker_llm_service_for_provider,
    get_worker_rag_planning_service,
    get_worker_rag_service,
    get_worker_session_factory,
)

logger = logging.getLogger(__name__)


def _build_usage_details(result: GenerationResult) -> dict[str, int]:
    """从 GenerationResult 构建 Langfuse usage_details dict。"""
    details: dict[str, int] = {}
    if result.tokens_input is not None:
        details["prompt_tokens"] = result.tokens_input
    if result.tokens_output is not None:
        details["completion_tokens"] = result.tokens_output
    if details:
        details["total_tokens"] = details.get("prompt_tokens", 0) + details.get(
            "completion_tokens", 0
        )
    return details


def _unpack_stream_args(
    args: tuple[object, ...],
) -> tuple[dict, str, dict[str, str] | None, str | None, str | None, str | None]:
    """Unpack old-style positional args for stream task."""
    generation_payload: dict = args[0]  # type: ignore[assignment]
    channel: str = args[1]  # type: ignore[assignment]
    trace_context: dict[str, str] | None = args[2] if len(args) > 2 else None  # type: ignore[assignment]
    assistant_message_id: str | None = args[3] if len(args) > 3 else None  # type: ignore[assignment]
    user_id: str | None = args[4] if len(args) > 4 else None  # type: ignore[assignment]
    idempotency_lock_key: str | None = args[5] if len(args) > 5 else None  # type: ignore[assignment]
    return (
        generation_payload,
        channel,
        trace_context,
        assistant_message_id,
        user_id,
        idempotency_lock_key,
    )


def _unpack_nonstream_args(
    args: tuple[object, ...],
) -> tuple[dict, dict[str, str] | None, str | None, str | None, str | None]:
    """Unpack old-style positional args for non-stream task."""
    generation_payload: dict = args[0]  # type: ignore[assignment]
    trace_context: dict[str, str] | None = args[1] if len(args) > 1 else None  # type: ignore[assignment]
    assistant_message_id: str | None = args[2] if len(args) > 2 else None  # type: ignore[assignment]
    user_id: str | None = args[3] if len(args) > 3 else None  # type: ignore[assignment]
    idempotency_lock_key: str | None = args[4] if len(args) > 4 else None  # type: ignore[assignment]
    return (
        generation_payload,
        trace_context,
        assistant_message_id,
        user_id,
        idempotency_lock_key,
    )


# ── Streaming ──────────────────────────────────────────────────────


@broker.task(task_name="generate_llm_stream")
async def generate_llm_stream_task(*args: object) -> None:
    """TaskIQ 入口：恢复 trace context 后执行流式生成。

    Backward-compatible: accepts old positional args (len > 1)
    or new single LLMTaskPayload dict (len == 1).
    """
    if len(args) > 1:
        (
            generation_payload,
            channel,
            trace_context,
            assistant_message_id,
            user_id,
            idempotency_lock_key,
        ) = _unpack_stream_args(args)
        generation_attempt = None
    else:
        task_payload = LLMTaskPayload.model_validate(args[0])
        generation_payload = task_payload.generation_payload
        channel = task_payload.channel
        trace_context = task_payload.trace_context
        assistant_message_id = task_payload.assistant_message_id
        user_id = task_payload.user_id
        idempotency_lock_key = task_payload.idempotency_lock_key
        generation_attempt = task_payload.generation_attempt

    assert channel is not None, "stream task requires a channel"
    with use_trace_context(trace_context):
        payload = GenerationPayload(**generation_payload)
        with (
            set_langfuse_trace_metadata(
                user_id=user_id,
                session_id=payload.session_id,
                tags=["chat_api", "worker", "stream"],
            ),
            langfuse_generation(
                name="generate_llm_stream",
                input_payload=generation_payload,
                model=generation_payload.get("billing_model_name"),
                metadata={"stream": True, "session_id": str(payload.session_id)},
            ) as recorder,
        ):
            result = await _generate_llm_stream_task(
                payload=payload,
                channel=channel,
                assistant_message_id=assistant_message_id,
                user_id=user_id,
                idempotency_lock_key=idempotency_lock_key,
                generation_attempt=generation_attempt,
            )
            if not result.success:
                recorder.record(error=result.error)
            else:
                usage_dict = {}
                if result.tokens_input is not None:
                    usage_dict["prompt_tokens"] = result.tokens_input
                if result.tokens_output is not None:
                    usage_dict["completion_tokens"] = result.tokens_output
                if usage_dict:
                    usage_dict["total_tokens"] = usage_dict.get(
                        "prompt_tokens", 0
                    ) + usage_dict.get("completion_tokens", 0)

                recorder.record(
                    output=result.output,
                    usage=usage_dict if usage_dict else None,
                    model=result.model_name,
                    metadata=result.langfuse_metadata,
                )


async def _generate_llm_stream_task(
    *,
    payload: GenerationPayload,
    channel: str,
    assistant_message_id: str | None = None,
    user_id: str | None = None,
    idempotency_lock_key: str | None = None,
    generation_attempt: GenerationAttemptPayload | None = None,
) -> StreamGenerationResult:
    """执行流式生成，返回 StreamGenerationResult。"""
    logger.info("TaskIQ Worker 开始处理流式请求: %s", channel)

    llm_service = get_worker_llm_service()
    session_factory = get_worker_session_factory()
    workflow = LLMGenerationWorkerWorkflow(
        uow=SQLAlchemyUnitOfWork(session_factory),
        redis_client=redis_client,
        llm_service=llm_service,
        llm_service_resolver=get_worker_llm_service_for_provider,
        rag_service=get_worker_rag_service(),
        rag_planning_service=get_worker_rag_planning_service(),
        external_context_provider=get_worker_external_context_provider(),
        heartbeat_uow_factory=lambda: SQLAlchemyUnitOfWork(session_factory),
    )
    assistant_uuid = uuid.UUID(assistant_message_id) if assistant_message_id else None
    user_uuid = uuid.UUID(user_id) if user_id else None

    return await workflow.generate_stream(
        payload=payload,
        channel=channel,
        assistant_message_id=assistant_uuid,
        user_id=user_uuid,
        idempotency_lock_key=idempotency_lock_key,
        generation_attempt=generation_attempt,
    )


# ── Non-Streaming ──────────────────────────────────────────────────


@broker.task(task_name="generate_llm_nonstream")
async def generate_llm_nonstream_task(*args: object) -> GenerationResult:
    """TaskIQ 入口：恢复 trace context 后执行非流式生成，返回结果 dict。

    Backward-compatible: accepts old positional args (len > 1)
    or new single LLMTaskPayload dict (len == 1).
    """
    if len(args) > 1:
        (
            generation_payload,
            trace_context,
            assistant_message_id,
            user_id,
            idempotency_lock_key,
        ) = _unpack_nonstream_args(args)
        generation_attempt = None
    else:
        task_payload = LLMTaskPayload.model_validate(args[0])
        generation_payload = task_payload.generation_payload
        trace_context = task_payload.trace_context
        assistant_message_id = task_payload.assistant_message_id
        user_id = task_payload.user_id
        idempotency_lock_key = task_payload.idempotency_lock_key
        generation_attempt = task_payload.generation_attempt

    with use_trace_context(trace_context):
        payload = GenerationPayload(**generation_payload)
        with (
            set_langfuse_trace_metadata(
                user_id=user_id,
                session_id=payload.session_id,
                tags=["chat_api", "worker", "non-stream"],
            ),
            langfuse_generation(
                name="generate_llm_nonstream",
                input_payload=generation_payload,
                model=generation_payload.get("billing_model_name"),
                metadata={"stream": False, "session_id": str(payload.session_id)},
            ) as recorder,
        ):
            result = await _generate_llm_nonstream_task(
                payload=payload,
                assistant_message_id=assistant_message_id,
                user_id=user_id,
                idempotency_lock_key=idempotency_lock_key,
                generation_attempt=generation_attempt,
            )
            if result.success:
                recorder.record(
                    output=result.content,
                    usage=_build_usage_details(result),
                    model=result.model_name,
                    metadata=result.langfuse_metadata,
                )
            else:
                recorder.record(error=result.error or "LLM 服务返回失败")
            return result


async def _generate_llm_nonstream_task(
    *,
    payload: GenerationPayload,
    assistant_message_id: str | None = None,
    user_id: str | None = None,
    idempotency_lock_key: str | None = None,
    generation_attempt: GenerationAttemptPayload | None = None,
) -> GenerationResult:
    logger.info(
        "TaskIQ Worker 开始处理非流式请求: message_id=%s",
        assistant_message_id,
    )

    llm_service = get_worker_llm_service()
    session_factory = get_worker_session_factory()
    workflow = LLMGenerationWorkerWorkflow(
        uow=SQLAlchemyUnitOfWork(session_factory),
        redis_client=redis_client,
        llm_service=llm_service,
        llm_service_resolver=get_worker_llm_service_for_provider,
        rag_service=get_worker_rag_service(),
        rag_planning_service=get_worker_rag_planning_service(),
        external_context_provider=get_worker_external_context_provider(),
        heartbeat_uow_factory=lambda: SQLAlchemyUnitOfWork(session_factory),
    )
    assistant_uuid = uuid.UUID(assistant_message_id) if assistant_message_id else None
    user_uuid = uuid.UUID(user_id) if user_id else None

    return await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=assistant_uuid,
        user_id=user_uuid,
        idempotency_lock_key=idempotency_lock_key,
        generation_attempt=generation_attempt,
    )
