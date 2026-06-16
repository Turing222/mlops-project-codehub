"""Worker-side LLM generation workflow.

职责：在 TaskIQ worker 中调用 LLM、发布流式 chunk / 返回完整结果，并拥有最终消息状态落库。
边界：Web 负责创建会话和消息占位；本 workflow 不做认证/鉴权/HTTP 响应。
失败处理：业务和系统异常都会尽力回写助手消息失败状态，并通过 Redis 通知等待方。
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.application.chat.timing import (
    elapsed_ms,
    merge_metrics,
    perf_start,
    tokens_per_second,
)
from backend.application.chat.worker_guardrail_handler import WorkerGuardrailHandler
from backend.application.chat.worker_persistence_handler import WorkerPersistenceHandler
from backend.application.chat.worker_rag_orchestrator import (
    PreparedGenerationContext,
    StepCallback,
    WorkerRAGOrchestrator,
)
from backend.application.chat.worker_stream_publisher import WorkerStreamPublisher
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.contracts.interfaces import (
    AbstractExternalContextProvider,
    AbstractLLMService,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.core.concurrency import llm_concurrency_slot
from backend.core.exceptions import AppException
from backend.infra.redis import RedisClient
from backend.models.schemas.chat.dto import LLMQueryDTO
from backend.models.schemas.chat.payloads import (
    FeatureFlags,
    GenerationPayload,
    GenerationResult,
    StreamGenerationResult,
)
from backend.observability.trace_utils import (
    build_llm_span_attributes,
    set_span_attributes,
    trace_span,
)
from backend.services.chat_safety_metadata import (
    INJECTION_REFUSAL_MESSAGE,
    SAFETY_REFUSAL_MESSAGE,
    GuardrailDecision,
    GuardrailReason,
    build_guardrail_success_metadata,
    evaluate_input_guardrail,
    evaluate_output_guardrail,
)
from backend.services.citation_validator import (
    CitationResult,
    StreamingCitationFilter,
    extract_valid_ref_ids,
    validate_citations,
)
from backend.services.rag_evidence_policy import RAGEvidencePolicy
from backend.services.rag_planning_service import (
    DEFAULT_MODEL_ROUTE_REASON,
    RAGPlanningService,
)
from backend.utils.token_estimation import estimate_tokens

logger = logging.getLogger(__name__)


def _step_metrics_from_search_context(
    search_context: dict | None,
    **extra: object,
) -> dict[str, object]:
    """Build SSE step metrics, reading RAG timings from nested search_context.metrics."""
    metrics: dict[str, object] = {}
    if search_context is not None:
        nested = search_context.get("metrics")
        if isinstance(nested, dict):
            context_build_ms = nested.get("context_build_ms")
            if context_build_ms is not None:
                metrics["context_build_ms"] = context_build_ms
    for key, value in extra.items():
        if value is not None:
            metrics[key] = value
    return metrics


def _provider_for_model_tier(tier: str) -> str:
    if tier == "fast":
        return ai_settings.LLM_MODEL_ROUTE_FAST_PROVIDER
    if tier == "reasoning":
        return ai_settings.LLM_MODEL_ROUTE_REASONING_PROVIDER
    return ai_settings.LLM_MODEL_ROUTE_BALANCED_PROVIDER


def _normalize_model_tier(tier: str) -> str:
    return tier if tier in {"fast", "balanced", "reasoning"} else "balanced"


def _default_model_name() -> str:
    try:
        return get_llm_model_config().resolve_profile().model
    except Exception as exc:
        logger.debug("Failed to resolve default LLM model name: %s", exc)
        return "default"


@dataclass
class _RAGRefusalSignal(Exception):
    """Signal from _prepare_generation when RAG refuses to answer."""

    search_context: dict | None


@dataclass(frozen=True, slots=True)
class _SelectedLLM:
    service: AbstractLLMService
    tier: str
    provider: str
    provider_config: str
    model_name: str
    route_confidence: float
    route_reason: str
    fallback: bool = False


@dataclass(frozen=True, slots=True)
class _PreparedGeneration:
    llm_query: LLMQueryDTO
    tokens_input: int
    search_context: dict | None
    selected_llm: _SelectedLLM


class LLMGenerationWorkerWorkflow:
    """Worker-side LLM generation and persistence workflow."""

    def __init__(
        self,
        *,
        uow: AbstractUnitOfWork,
        redis_client: RedisClient,
        llm_service: AbstractLLMService,
        rag_service: AbstractRAGService | None = None,
        rag_planning_service: RAGPlanningService | None = None,
        external_context_provider: AbstractExternalContextProvider | None = None,
        chat_context_builder: ChatContextBuilder | None = None,
        rag_evidence_policy: RAGEvidencePolicy | None = None,
        rag_orchestrator: WorkerRAGOrchestrator | None = None,
        persistence_handler: WorkerPersistenceHandler | None = None,
        stream_publisher: WorkerStreamPublisher | None = None,
        guardrail_handler: WorkerGuardrailHandler | None = None,
        llm_service_resolver: Callable[[str | None], AbstractLLMService] | None = None,
    ) -> None:
        self._redis_client = redis_client
        self.uow = uow
        self.llm_service = llm_service
        self.llm_service_resolver = llm_service_resolver
        self.rag_orchestrator = rag_orchestrator or WorkerRAGOrchestrator(
            rag_service=rag_service,
            rag_planning_service=rag_planning_service,
            external_context_provider=external_context_provider,
            chat_context_builder=chat_context_builder,
            rag_evidence_policy=rag_evidence_policy,
        )
        self.persistence_handler = persistence_handler or WorkerPersistenceHandler(
            uow=uow,
            redis_client=redis_client,
        )
        self.stream_publisher = stream_publisher or WorkerStreamPublisher(
            redis_client=redis_client,
        )
        self.guardrail_handler = guardrail_handler or WorkerGuardrailHandler(
            persistence_handler=self.persistence_handler,
            stream_publisher=self.stream_publisher,
            count_output_tokens=self._count_output_tokens,
        )

    # ── Shared Internal Helpers ───────────────────────────────────

    async def _prepare_generation(
        self,
        payload: GenerationPayload,
        *,
        on_step: StepCallback | None = None,
    ) -> _PreparedGeneration:
        """RAG context -> selected LLM + query + tokens + search context.

        Raises _RAGRefusalSignal when RAG refuses to answer.
        Raises RuntimeError when assembled prompt is missing.
        """
        prepared_context = (
            await self.rag_orchestrator.prepare_context(payload, on_step=on_step)
            if on_step is not None
            else await self.rag_orchestrator.prepare_context(payload)
        )
        if prepared_context.refusal_decision is not None:
            raise _RAGRefusalSignal(search_context=prepared_context.search_context)
        assembled = prepared_context.assembled_prompt
        if assembled is None:
            raise RuntimeError("生成上下文缺少 Prompt")
        search_context = prepared_context.search_context
        tokens_input = assembled.total_tokens
        llm_query = LLMQueryDTO(
            session_id=payload.session_id,
            query_text=payload.query_text,
            conversation_history=assembled.messages,
            extra_body=payload.extra_body,
        )
        selected_llm = self._select_llm(prepared_context, payload.feature_flags)
        if search_context is not None:
            search_context = merge_metrics(
                search_context,
                self._model_route_metrics(selected_llm),
            )
        return _PreparedGeneration(
            llm_query=llm_query,
            tokens_input=tokens_input,
            search_context=search_context,
            selected_llm=selected_llm,
        )

    def _coerce_prepared_generation(self, prepared: object) -> _PreparedGeneration:
        if isinstance(prepared, _PreparedGeneration):
            return prepared
        if isinstance(prepared, tuple) and len(prepared) == 3:
            llm_query, tokens_input, search_context = prepared
            return _PreparedGeneration(
                llm_query=llm_query,  # type: ignore[arg-type]
                tokens_input=tokens_input,  # type: ignore[arg-type]
                search_context=search_context,  # type: ignore[arg-type]
                selected_llm=self._default_selected_llm(),
            )
        raise TypeError("Invalid prepared generation payload")

    def _default_selected_llm(self) -> _SelectedLLM:
        return _SelectedLLM(
            service=self.llm_service,
            tier="balanced",
            provider=getattr(self.llm_service, "provider_name", "unknown"),
            provider_config="default",
            model_name=getattr(self.llm_service, "model_name", _default_model_name()),
            route_confidence=1.0,
            route_reason=DEFAULT_MODEL_ROUTE_REASON,
        )

    def _select_llm(
        self, prepared_context: PreparedGenerationContext, feature_flags: FeatureFlags
    ) -> _SelectedLLM:
        tier = _normalize_model_tier(prepared_context.answer_model_tier)
        route_confidence = float(prepared_context.model_route_confidence or 0.0)
        route_reason = str(prepared_context.model_route_reason or "")
        provider_config = (
            _provider_for_model_tier(tier)
            if feature_flags.enable_llm_model_routing
            and route_confidence >= ai_settings.LLM_MODEL_ROUTE_MIN_CONFIDENCE
            else None
        )
        service = self.llm_service
        fallback = False
        if provider_config is not None:
            if self.llm_service_resolver is None:
                provider_config = None
                fallback = True
            else:
                try:
                    service = self.llm_service_resolver(provider_config)
                except Exception as exc:
                    fallback = True
                    logger.warning(
                        "Model tier routing failed, falling back to default LLM: tier=%s provider=%s error=%s",
                        tier,
                        provider_config,
                        exc,
                    )
                    provider_config = None
        return _SelectedLLM(
            service=service,
            tier=tier if provider_config is not None else "balanced",
            provider=getattr(service, "provider_name", "unknown"),
            provider_config=provider_config or "default",
            model_name=getattr(service, "model_name", _default_model_name()),
            route_confidence=route_confidence,
            route_reason=route_reason,
            fallback=fallback,
        )

    async def _handle_generation_error(
        self,
        exc: Exception,
        *,
        assistant_message_id: uuid.UUID | None,
        idempotency_lock_key: str | None,
        channel: str | None = None,
    ) -> GenerationResult:
        """Common error handling: persist failure, optionally publish, return result."""
        if isinstance(exc, AppException):
            logger.warning("TaskIQ 调用 LLM 业务异常: %s", exc)
            error_content = str(exc)
        else:
            logger.exception("TaskIQ 调用 LLM 系统异常")
            error_content = "服务暂时不可用，请稍后重试"

        await self.persistence_handler.persist_failure(
            assistant_message_id=assistant_message_id,
            error_content=error_content,
            idempotency_lock_key=idempotency_lock_key,
        )

        if channel is not None:
            await self.stream_publisher.publish_error(channel, error_content)

        return GenerationResult(success=False, error=error_content)

    def _build_span_attributes(
        self,
        *,
        llm_service: AbstractLLMService,
        stream: bool,
        session_id: uuid.UUID,
        assistant_message_id: uuid.UUID | None,
        tokens_input: int,
        search_context: dict | None,
        channel: str | None = None,
    ) -> dict[str, object]:
        """Build OTel span attributes shared by stream and non-stream paths."""
        attrs: dict[str, object] = {
            **build_llm_span_attributes(
                provider=getattr(llm_service, "provider_name", "unknown"),
                model=getattr(llm_service, "model_name", "unknown"),
                operation="generate",
                stream=stream,
            ),
            "chat.session_id": session_id,
            "chat.assistant_message_id": assistant_message_id,
            "chat.prompt.tokens_input": tokens_input,
            "chat.prompt.uses_rag": search_context is not None,
            "llm.provider": getattr(llm_service, "provider_name", "unknown"),
        }
        if channel is not None:
            attrs["redis.channel"] = channel
        return attrs

    async def _persist_success_and_idempotency(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        content: str,
        tokens_input: int,
        tokens_output: int,
        search_context: dict | None,
        start_time: float,
        message_metadata: dict | None,
        idempotency_lock_key: str | None,
        model_name: str = "default",
    ) -> None:
        """Persist success state and write idempotency marker if applicable."""
        await self.persistence_handler.persist_success(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=content,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=message_metadata,
            model_name=model_name,
        )
        if idempotency_lock_key is not None and assistant_message_id is not None:
            await self.persistence_handler.write_idempotency_message(
                idempotency_lock_key=idempotency_lock_key,
                assistant_message_id=assistant_message_id,
            )

    def _count_output_tokens(
        self,
        content: str,
        llm_service: AbstractLLMService | None = None,
    ) -> int:
        service = llm_service or self.llm_service
        model_name = getattr(
            service,
            "model_name",
            get_llm_model_config().resolve_profile().model,
        )
        return estimate_tokens(content, model_name)

    @staticmethod
    def _model_route_metrics(selected_llm: _SelectedLLM) -> dict[str, object]:
        return {
            "answer_model_tier": selected_llm.tier,
            "answer_model_provider": selected_llm.provider_config,
            "answer_model_name": selected_llm.model_name,
            "model_route_confidence": selected_llm.route_confidence,
            "model_route_reason": selected_llm.route_reason,
            "model_route_fallback": selected_llm.fallback,
        }

    @staticmethod
    def _enrich_metadata_with_citation(
        metadata: dict[str, object],
        *,
        citation_result: CitationResult | None,
    ) -> dict[str, object]:
        if citation_result is not None:
            metadata["citation"] = {
                "total": citation_result.total_citations,
                "removed_count": citation_result.removed_count,
            }
        return metadata

    @staticmethod
    def _build_langfuse_metadata(
        *,
        selected_llm: _SelectedLLM,
        first_token_ms: int | None,
        output_decision: GuardrailDecision | None,
        output_blocked: bool,
        search_context: dict | None,
        citation_result: CitationResult | None,
    ) -> dict[str, object]:
        """构建 Langfuse metadata，包含模型路由、guardrail、RAG、citation 信息。"""
        metadata: dict[str, object] = {
            "model_tier": selected_llm.tier,
            "provider_config": selected_llm.provider_config,
            "route_confidence": selected_llm.route_confidence,
            "route_reason": selected_llm.route_reason,
            "route_fallback": selected_llm.fallback,
            "first_token_ms": first_token_ms,
            "guardrail_output_triggered": (
                output_decision.triggered if output_decision else False
            ),
            "guardrail_output_blocked": output_blocked,
        }

        if search_context is not None:
            metadata["rag_hit_count"] = search_context.get("rag_hit_count")
            metadata["rag_rerank_enabled"] = search_context.get("rag_rerank_enabled")

        if citation_result is not None:
            metadata["citation_total"] = citation_result.total_citations
            metadata["citation_removed"] = citation_result.removed_count

        return metadata

    # ── Streaming ──────────────────────────────────────────────────

    async def generate_stream(
        self,
        *,
        payload: GenerationPayload,
        channel: str,
        assistant_message_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        idempotency_lock_key: str | None = None,
    ) -> StreamGenerationResult:
        """Generate a streaming answer, publish chunks, and persist final state.

        Returns StreamGenerationResult with success status, output, tokens, and metadata.
        """
        accumulated_content: list[str] = []
        done_published: bool = False
        output_decision: GuardrailDecision | None = None
        output_blocked = False
        start_time = time.time()
        worker_started = perf_start()

        try:
            await self.stream_publisher.publish_started(channel)
            input_decision = evaluate_input_guardrail(payload.query_text)
            if input_decision.triggered:
                refusal_message = (
                    INJECTION_REFUSAL_MESSAGE
                    if input_decision.reason == GuardrailReason.INJECTION_RISK.value
                    else SAFETY_REFUSAL_MESSAGE
                )
                tokens_output = self._count_output_tokens(refusal_message)
                await self.guardrail_handler.handle_stream_input_block(
                    channel=channel,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    input_decision=input_decision,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
                return StreamGenerationResult(
                    success=True,
                    output=refusal_message,
                    tokens_input=0,
                    tokens_output=tokens_output,
                    langfuse_metadata={
                        "response_outcome": "blocked",
                        "guardrail_input_triggered": True,
                        "guardrail_input_reason": input_decision.reason,
                    },
                )
            try:
                async def on_step(
                    step: str,
                    status: str,
                    metrics: dict[str, object] | None = None,
                ) -> None:
                    await self.stream_publisher.publish_step(
                        channel,
                        step,
                        status,  # type: ignore[arg-type]
                        metrics,
                    )

                prepared = self._coerce_prepared_generation(
                    await self._prepare_generation(payload, on_step=on_step)
                )
            except _RAGRefusalSignal as sig:
                planner_refusal = bool(
                    sig.search_context and sig.search_context.get("planner_refusal")
                )
                refusal_content = (
                    ai_settings.RAG_PLANNER_REFUSAL_MESSAGE
                    if planner_refusal
                    else ai_settings.RAG_REFUSAL_MESSAGE
                )
                tokens_output = self._count_output_tokens(refusal_content)
                await self.guardrail_handler.handle_stream_refusal(
                    channel=channel,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    search_context=sig.search_context,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
                return StreamGenerationResult(
                    success=True,
                    output=refusal_content,
                    tokens_input=0,
                    tokens_output=tokens_output,
                    langfuse_metadata={
                        "response_outcome": "refused",
                        "rag_refusal": True,
                        "planner_refusal": planner_refusal,
                    },
                )

            llm_query = prepared.llm_query
            tokens_input = prepared.tokens_input
            search_context = prepared.search_context
            selected_llm = prepared.selected_llm
            model_route_metrics = self._model_route_metrics(selected_llm)

            with trace_span(
                "taskiq.llm_stream.generate_and_publish",
                self._build_span_attributes(
                    llm_service=selected_llm.service,
                    stream=True,
                    session_id=payload.session_id,
                    assistant_message_id=assistant_message_id,
                    tokens_input=tokens_input,
                    search_context=search_context,
                    channel=channel,
                ),
            ) as span:
                citation_filter: StreamingCitationFilter | None = None
                if search_context is not None:
                    valid_ref_ids = extract_valid_ref_ids(search_context)
                    if valid_ref_ids:
                        citation_filter = StreamingCitationFilter(valid_ref_ids)
                llm_started = perf_start()
                # Worker first token: worker generation start -> first user-visible
                # chunk publish. Web records e2e_first_token_ms from HTTP entry.
                first_token_latency_ms: int | None = None
                first_published_from_llm_ms: int | None = None

                in_thinking = False
                thinking_started_time = None
                thinking_duration_ms = None
                answer_started_time = None
                answer_duration_ms = None
                thinking_step_running = False
                thinking_step_done = False
                generate_answer_running = False

                async def publish_user_chunk(content: str) -> None:
                    nonlocal first_token_latency_ms
                    nonlocal first_published_from_llm_ms
                    nonlocal generate_answer_running
                    if first_token_latency_ms is None:
                        first_token_latency_ms = elapsed_ms(worker_started)
                        first_published_from_llm_ms = elapsed_ms(llm_started)
                    if not generate_answer_running:
                        generate_answer_running = True
                        await on_step("generate-answer", "running")
                    await self.stream_publisher.publish_chunk(channel, content)

                async with llm_concurrency_slot(
                    {
                        "chat.session_id": payload.session_id,
                        "chat.assistant_message_id": assistant_message_id,
                        "chat.stream": True,
                        "llm.model_tier": selected_llm.tier,
                    }
                ):
                    async for chunk in selected_llm.service.stream_response(llm_query):
                        candidate_content = "".join([*accumulated_content, chunk])
                        output_decision = evaluate_output_guardrail(candidate_content)
                        if output_decision.triggered:
                            accumulated_content.append(chunk)
                            output_blocked = True
                            await publish_user_chunk(SAFETY_REFUSAL_MESSAGE)
                            break
                        accumulated_content.append(chunk)

                        full_so_far = "".join(accumulated_content)
                        if not in_thinking and thinking_duration_ms is None:
                            if "<think>" in full_so_far:
                                in_thinking = True
                                thinking_started_time = perf_start()
                                if not thinking_step_running:
                                    thinking_step_running = True
                                    await on_step("model-thinking", "running")
                            elif answer_started_time is None:
                                answer_started_time = perf_start()
                        elif in_thinking and "</think>" in full_so_far:
                            in_thinking = False
                            thinking_duration_ms = elapsed_ms(thinking_started_time)
                            answer_started_time = perf_start()
                            if thinking_step_running and not thinking_step_done:
                                thinking_step_done = True
                                await on_step(
                                    "model-thinking",
                                    "done",
                                    {"thinking_duration_ms": thinking_duration_ms},
                                )

                        if citation_filter is not None:
                            cleaned = citation_filter.push(chunk)
                            if cleaned is not None:
                                await publish_user_chunk(cleaned)
                        else:
                            await publish_user_chunk(chunk)
                    if not output_blocked and citation_filter is not None:
                        remaining = citation_filter.flush()
                        if remaining:
                            await publish_user_chunk(remaining)
                llm_generate_ms = elapsed_ms(llm_started)

                # Finalize thinking and answer durations
                if in_thinking:
                    thinking_duration_ms = (
                        elapsed_ms(thinking_started_time)
                        if thinking_started_time is not None
                        else 0
                    )
                    answer_duration_ms = 0
                else:
                    if thinking_duration_ms is None:
                        thinking_duration_ms = 0
                        answer_duration_ms = (
                            elapsed_ms(answer_started_time)
                            if answer_started_time is not None
                            else 0
                        )
                    else:
                        answer_duration_ms = (
                            elapsed_ms(answer_started_time)
                            if answer_started_time is not None
                            else 0
                        )

                if thinking_step_running and not thinking_step_done:
                    if thinking_duration_ms is None:
                        thinking_duration_ms = (
                            elapsed_ms(thinking_started_time)
                            if thinking_started_time is not None
                            else 0
                        )
                    thinking_step_done = True
                    await on_step(
                        "model-thinking",
                        "done",
                        {"thinking_duration_ms": thinking_duration_ms},
                    )

                if generate_answer_running:
                    await on_step(
                        "generate-answer",
                        "done",
                        {
                            "answer_duration_ms": answer_duration_ms,
                            "llm_generate_ms": llm_generate_ms,
                        },
                    )

                full_content = "".join(accumulated_content)
                if output_blocked:
                    if output_decision is None:
                        output_decision = evaluate_output_guardrail(full_content)
                    content_to_persist = SAFETY_REFUSAL_MESSAGE
                else:
                    output_decision = evaluate_output_guardrail(full_content)
                    content_to_persist = full_content
                citation_result: CitationResult | None = None
                if (
                    not output_blocked
                    and search_context is not None
                    and content_to_persist
                ):
                    valid_ref_ids = extract_valid_ref_ids(search_context)
                    if valid_ref_ids:
                        await on_step("organize-citations", "running")
                        citation_validate_started = perf_start()
                        citation_result = validate_citations(
                            content_to_persist, valid_ref_ids
                        )
                        citation_validate_ms = elapsed_ms(citation_validate_started)
                        search_context = merge_metrics(
                            search_context,
                            {"citation_validate_ms": citation_validate_ms},
                        )
                        await on_step(
                            "organize-citations",
                            "done",
                            _step_metrics_from_search_context(
                                search_context,
                                citation_validate_ms=citation_validate_ms,
                                citation_total=citation_result.total_citations,
                                citation_removed=citation_result.removed_count,
                            ),
                        )
                        content_to_persist = citation_result.cleaned_content
                elif search_context is not None and not output_blocked:
                    await on_step("organize-citations", "running")
                    await on_step(
                        "organize-citations",
                        "done",
                        _step_metrics_from_search_context(search_context),
                    )
                tokens_output = self._count_output_tokens(content_to_persist)
                worker_total_latency_ms = elapsed_ms(worker_started)
                await self._persist_success_and_idempotency(
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    content=content_to_persist,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    search_context=search_context,
                    start_time=start_time,
                    message_metadata=merge_metrics(
                        self._enrich_metadata_with_citation(
                            build_guardrail_success_metadata(
                                output_decision=output_decision,
                                original_content=full_content,
                            ),
                            citation_result=citation_result,
                        ),
                        {
                            **model_route_metrics,
                            "worker_total_latency_ms": worker_total_latency_ms,
                            "llm_first_token_ms": first_published_from_llm_ms,
                            "first_token_latency_ms": first_token_latency_ms,
                            "llm_generate_ms": llm_generate_ms,
                            "llm_thinking_ms": thinking_duration_ms,
                            "llm_answer_ms": answer_duration_ms,
                            "tokens_input": tokens_input,
                            "tokens_output": tokens_output,
                            "tokens_per_second": tokens_per_second(
                                tokens_output,
                                llm_generate_ms,
                            ),
                        },
                    ),
                    idempotency_lock_key=idempotency_lock_key,
                    model_name=selected_llm.model_name,
                )

                set_span_attributes(
                    span,
                    {
                        "llm.first_token_ms": first_published_from_llm_ms,
                        "chat.first_token_latency_ms": first_token_latency_ms,
                        "chat.worker_total_latency_ms": worker_total_latency_ms,
                        "llm.provider": selected_llm.provider,
                        "llm.model_tier": selected_llm.tier,
                        "llm.route.provider_config": selected_llm.provider_config,
                        "gen_ai.request.model": selected_llm.model_name,
                    },
                )
            logger.info("TaskIQ Worker 成功结束流式处理: %s", channel)
            return StreamGenerationResult(
                success=True,
                output=content_to_persist,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                model_name=selected_llm.model_name,
                langfuse_metadata=self._build_langfuse_metadata(
                    selected_llm=selected_llm,
                    first_token_ms=first_published_from_llm_ms,
                    output_decision=output_decision,
                    output_blocked=output_blocked,
                    search_context=search_context,
                    citation_result=citation_result,
                ),
            )
        except (AppException, Exception) as exc:
            result = await self._handle_generation_error(
                exc,
                assistant_message_id=assistant_message_id,
                idempotency_lock_key=idempotency_lock_key,
                channel=channel,
            )
            return StreamGenerationResult(success=False, error=result.error)
        finally:
            if not done_published:
                await self.stream_publisher.publish_done(channel)

    # ── Non-Streaming ──────────────────────────────────────────────

    async def generate_nonstream(
        self,
        *,
        payload: GenerationPayload,
        assistant_message_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        idempotency_lock_key: str | None = None,
    ) -> GenerationResult:
        """Generate a non-streaming answer, persist final state, and return result."""
        start_time = time.time()
        worker_started = perf_start()

        try:
            input_decision = evaluate_input_guardrail(payload.query_text)
            if input_decision.triggered:
                return await self.guardrail_handler.handle_nonstream_input_block(
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    input_decision=input_decision,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
            try:
                prepared = self._coerce_prepared_generation(
                    await self._prepare_generation(payload)
                )
            except _RAGRefusalSignal as sig:
                return await self.guardrail_handler.handle_nonstream_refusal(
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    search_context=sig.search_context,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )

            llm_query = prepared.llm_query
            tokens_input = prepared.tokens_input
            search_context = prepared.search_context
            selected_llm = prepared.selected_llm
            model_route_metrics = self._model_route_metrics(selected_llm)

            with trace_span(
                "taskiq.llm_nonstream.generate",
                self._build_span_attributes(
                    llm_service=selected_llm.service,
                    stream=False,
                    session_id=payload.session_id,
                    assistant_message_id=assistant_message_id,
                    tokens_input=tokens_input,
                    search_context=search_context,
                ),
            ) as span:
                async with llm_concurrency_slot(
                    {
                        "chat.session_id": payload.session_id,
                        "chat.assistant_message_id": assistant_message_id,
                        "chat.stream": False,
                        "llm.model_tier": selected_llm.tier,
                    }
                ):
                    llm_started = perf_start()
                    result = await selected_llm.service.generate_response(llm_query)
                    llm_generate_ms = elapsed_ms(llm_started)
                set_span_attributes(
                    span,
                    {
                        "llm.success": result.success,
                        "llm.latency_ms": result.latency_ms,
                        "llm.generate_ms": llm_generate_ms,
                        "llm.provider": selected_llm.provider,
                        "llm.model_tier": selected_llm.tier,
                        "llm.route.provider_config": selected_llm.provider_config,
                        "gen_ai.request.model": selected_llm.model_name,
                    },
                )

            if not result.success:
                error_msg = result.error_message or "LLM 服务返回失败"
                await self.persistence_handler.persist_failure(
                    assistant_message_id=assistant_message_id,
                    error_content=error_msg,
                    idempotency_lock_key=idempotency_lock_key,
                )
                return GenerationResult(success=False, error=error_msg)

            original_content = result.content
            output_decision = evaluate_output_guardrail(original_content)
            full_content = (
                SAFETY_REFUSAL_MESSAGE
                if output_decision.triggered
                else original_content
            )
            citation_result: CitationResult | None = None
            if (
                not output_decision.triggered
                and search_context is not None
                and full_content
            ):
                valid_ref_ids = extract_valid_ref_ids(search_context)
                if valid_ref_ids:
                    citation_validate_started = perf_start()
                    citation_result = validate_citations(full_content, valid_ref_ids)
                    search_context = merge_metrics(
                        search_context,
                        {"citation_validate_ms": elapsed_ms(citation_validate_started)},
                    )
                    full_content = citation_result.cleaned_content
            tokens_input_for_billing = (
                result.prompt_tokens
                if result.prompt_tokens is not None
                else tokens_input
            )
            tokens_input_source = (
                "provider_usage" if result.prompt_tokens is not None else "estimate"
            )
            if output_decision.triggered:
                tokens_output = self._count_output_tokens(full_content)
                tokens_output_source = "estimate"
            elif result.completion_tokens is not None:
                tokens_output = result.completion_tokens
                tokens_output_source = "provider_usage"
            else:
                tokens_output = self._count_output_tokens(full_content)
                tokens_output_source = "estimate"
            worker_total_latency_ms = elapsed_ms(worker_started)

            await self._persist_success_and_idempotency(
                assistant_message_id=assistant_message_id,
                user_id=user_id,
                content=full_content,
                tokens_input=tokens_input_for_billing,
                tokens_output=tokens_output,
                search_context=search_context,
                start_time=start_time,
                message_metadata=merge_metrics(
                    self._enrich_metadata_with_citation(
                        build_guardrail_success_metadata(
                            output_decision=output_decision,
                            original_content=original_content,
                        ),
                        citation_result=citation_result,
                    ),
                    {
                        **model_route_metrics,
                        "worker_total_latency_ms": worker_total_latency_ms,
                        "llm_generate_ms": llm_generate_ms,
                        "tokens_input": tokens_input_for_billing,
                        "tokens_output": tokens_output,
                        "tokens_input_source": tokens_input_source,
                        "tokens_output_source": tokens_output_source,
                        "tokens_per_second": tokens_per_second(
                            tokens_output,
                            llm_generate_ms,
                        ),
                    },
                ),
                idempotency_lock_key=idempotency_lock_key,
                model_name=selected_llm.model_name,
            )

            logger.info(
                "TaskIQ Worker 成功结束非流式处理: session_id=%s, message_id=%s",
                payload.session_id,
                assistant_message_id,
            )
            return GenerationResult(
                success=True,
                content=full_content,
                tokens_input=tokens_input_for_billing,
                tokens_output=tokens_output,
                search_context=search_context,
                latency_ms=result.latency_ms,
                model_name=selected_llm.model_name,
                langfuse_metadata=self._build_langfuse_metadata(
                    selected_llm=selected_llm,
                    first_token_ms=None,
                    output_decision=output_decision,
                    output_blocked=output_decision.triggered
                    if output_decision
                    else False,
                    search_context=search_context,
                    citation_result=citation_result,
                ),
            )

        except (AppException, Exception) as exc:
            return await self._handle_generation_error(
                exc,
                assistant_message_id=assistant_message_id,
                idempotency_lock_key=idempotency_lock_key,
            )
