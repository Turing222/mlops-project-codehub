"""Worker-side RAG context orchestration.

职责：为 worker 生成流程准备 RAG plan、检索候选、rerank 结果和证据拒答上下文。
边界：本模块不调用 LLM 生成答案，不持久化消息，也不发布 Redis 流式事件。
"""

import logging
from dataclasses import dataclass
from typing import Any

from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.application.chat.timing import elapsed_ms, merge_metrics, perf_start
from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import (
    AbstractExternalContextProvider,
    AbstractRAGService,
)
from backend.core.concurrency import llm_concurrency_slot
from backend.models.schemas.chat.context_routing import (
    is_external_context_allowed,
    resolve_context_mode,
    source_selected,
)
from backend.models.schemas.chat.payloads import GenerationPayload
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.rag_evidence_policy import RAGEvidenceDecision, RAGEvidencePolicy
from backend.services.rag_planning_service import (
    DEFAULT_MODEL_ROUTE_REASON,
    RAG_PLANNER_FALLBACK_REASON,
    PlannerModelTier,
    RAGExecutionPlan,
    RAGPlanningService,
)
from backend.services.rag_service import select_rerank_fallback_candidates

logger = logging.getLogger(__name__)

_FLAGS_ATTRS: dict[str, str] = {
    "enable_external_context": "feature_flags.enable_external_context",
    "enable_rag_rerank": "feature_flags.enable_rag_rerank",
    "enable_rag_planner": "feature_flags.enable_rag_planner",
    "enable_rag_planner_routing": "feature_flags.enable_rag_planner_routing",
    "enable_rag_refusal": "feature_flags.enable_rag_refusal",
    "enable_llm_model_routing": "feature_flags.enable_llm_model_routing",
}


@dataclass
class PreparedGenerationContext:
    """Worker 生成前准备好的 Prompt 或拒答决策。"""

    assembled_prompt: Any | None
    search_context: dict | None
    refusal_decision: RAGEvidenceDecision | None = None
    answer_model_tier: PlannerModelTier = "balanced"
    model_route_confidence: float = 1.0
    model_route_reason: str = DEFAULT_MODEL_ROUTE_REASON


class WorkerRAGOrchestrator:
    """Worker-side RAG retrieval, rerank, and context assembly."""

    def __init__(
        self,
        *,
        rag_service: AbstractRAGService | None = None,
        rag_planning_service: RAGPlanningService | None = None,
        external_context_provider: AbstractExternalContextProvider | None = None,
        chat_context_builder: ChatContextBuilder | None = None,
        rag_evidence_policy: RAGEvidencePolicy | None = None,
    ) -> None:
        self.rag_service = rag_service
        self.rag_planning_service = rag_planning_service
        self.external_context_provider = external_context_provider
        self.chat_context_builder = chat_context_builder or ChatContextBuilder()
        self.rag_evidence_policy = rag_evidence_policy or RAGEvidencePolicy()

    async def prepare_context(
        self,
        payload: GenerationPayload,
    ) -> PreparedGenerationContext:
        with trace_span(
            "taskiq.llm_stream.prepare_context",
            {
                "chat.session_id": payload.session_id,
                "rag.kb_id": payload.kb_id,
            },
        ) as span:
            metrics: dict[str, object] = {}
            planner_started = perf_start()
            rag_plan, planner_used = await self.build_rag_plan(payload)
            self._debug_log_rag_plan(
                payload=payload,
                rag_plan=rag_plan,
                planner_used=planner_used,
            )
            metrics["planner_ms"] = elapsed_ms(planner_started)
            metrics["planner_used"] = planner_used
            metrics["retrieval_mode"] = rag_plan.retrieval_mode
            metrics["rerank_used"] = rag_plan.use_rerank
            metrics["context_mode"] = rag_plan.context_mode
            metrics["selected_sources"] = ",".join(rag_plan.selected_sources)
            metrics["route_reason"] = rag_plan.reason
            if payload.feature_flags.enable_rag_planner_routing:
                metrics["answer_route"] = rag_plan.answer_route
                metrics["route_confidence"] = rag_plan.route_confidence
            metrics["answer_model_tier"] = rag_plan.answer_model_tier
            metrics["model_route_confidence"] = rag_plan.model_route_confidence
            metrics["model_route_reason"] = rag_plan.model_route_reason
            metrics["external_context_planned"] = rag_plan.should_use_external_context

            preflight_refusal = self._build_planner_preflight_refusal(
                payload=payload,
                rag_plan=rag_plan,
            )
            if preflight_refusal is not None:
                search_context = self._build_planner_refusal_search_context(
                    payload=payload,
                    decision=preflight_refusal,
                    rag_plan=rag_plan,
                )
                search_context = self._with_rag_metrics(search_context, metrics)
                set_span_attributes(
                    span,
                    {
                        "rag.refusal": True,
                        "rag.refusal_reason": preflight_refusal.reason,
                        "rag.planner.used": planner_used,
                        "rag.planner.answer_route": rag_plan.answer_route,
                        "rag.planner.route_confidence": rag_plan.route_confidence,
                        "rag.planner.preflight_refusal": True,
                    },
                )
                return PreparedGenerationContext(
                    assembled_prompt=None,
                    search_context=search_context,
                    refusal_decision=preflight_refusal,
                    answer_model_tier=rag_plan.answer_model_tier,
                    model_route_confidence=rag_plan.model_route_confidence,
                    model_route_reason=rag_plan.model_route_reason,
                )

            retrieve_started = perf_start()
            rag_candidates = await self.retrieve_rag_candidates(payload, rag_plan)
            metrics["retrieve_ms"] = elapsed_ms(retrieve_started)
            metrics["rag_candidate_count"] = len(rag_candidates)

            external_started = perf_start()
            external_candidates = await self.retrieve_external_context_candidates(
                payload,
                rag_plan,
            )
            metrics["external_context_ms"] = elapsed_ms(external_started)
            metrics["external_context_hit_count"] = len(external_candidates)
            metrics["external_context_used"] = bool(external_candidates)
            provider = self.external_context_provider
            metrics["external_context_provider"] = (
                provider.provider_name if provider and external_candidates else None
            )

            candidates = [*rag_candidates, *external_candidates]
            metrics["candidate_count"] = len(candidates)

            rerank_started = perf_start()
            reranked_chunks = await self.rerank_candidates_if_enabled(
                payload,
                candidates,
                rag_plan,
            )
            metrics["rerank_ms"] = elapsed_ms(rerank_started)
            metrics["hit_count"] = len(reranked_chunks)
            self._debug_log_final_chunks(
                payload=payload,
                chunks=reranked_chunks,
                stage="final_rag_chunks",
            )

            refusal_decision = self.rag_evidence_policy.evaluate(
                kb_id=payload.kb_id,
                rag_plan=rag_plan,
                chunks=reranked_chunks,
                enable_rag_refusal=payload.feature_flags.enable_rag_refusal,
            )
            if refusal_decision.should_refuse:
                context_started = perf_start()
                search_context = self._build_refusal_search_context(
                    payload=payload,
                    chunks=reranked_chunks,
                    decision=refusal_decision,
                )
                metrics["context_build_ms"] = elapsed_ms(context_started)
                search_context = self._with_rag_metrics(search_context, metrics)
                set_span_attributes(
                    span,
                    {
                        "rag.refusal": True,
                        "rag.refusal_reason": refusal_decision.reason,
                        "rag.hit_count": len(reranked_chunks),
                        "rag.planner.used": planner_used,
                        "rag.planner.should_use_rag": rag_plan.should_use_rag,
                        "rag.planner.retrieval_mode": rag_plan.retrieval_mode,
                        "context.mode": rag_plan.context_mode,
                        "context.selected_sources": ",".join(rag_plan.selected_sources),
                        "rag.planner.answer_route": rag_plan.answer_route,
                        "rag.planner.route_confidence": rag_plan.route_confidence,
                        "external_context.hit_count": len(external_candidates),
                    },
                )
                return PreparedGenerationContext(
                    assembled_prompt=None,
                    search_context=search_context,
                    refusal_decision=refusal_decision,
                    answer_model_tier=rag_plan.answer_model_tier,
                    model_route_confidence=rag_plan.model_route_confidence,
                    model_route_reason=rag_plan.model_route_reason,
                )

            context_started = perf_start()
            prepared_context = self.chat_context_builder.build_from_chunks(
                history_messages=payload.conversation_history,
                current_query=payload.query_text,
                kb_id=payload.kb_id,
                rag_chunks=reranked_chunks,
                context_state=payload.context_state,
            )
            metrics["context_build_ms"] = elapsed_ms(context_started)
            search_context = self._with_rag_metrics(
                prepared_context.search_context,
                metrics,
            )
            set_span_attributes(
                span,
                {
                    "rag.candidate_count": len(candidates),
                    "rag.rerank.enabled": rag_plan.use_rerank,
                    "rag.rerank.config_enabled": payload.feature_flags.enable_rag_rerank,
                    "rag.hit_count": len(reranked_chunks),
                    "rag.planner.enabled": payload.feature_flags.enable_rag_planner,
                    "rag.planner.used": planner_used,
                    "rag.planner.should_use_rag": rag_plan.should_use_rag,
                    "rag.planner.retrieval_mode": rag_plan.retrieval_mode,
                    "rag.planner.use_rerank": rag_plan.use_rerank,
                    "rag.planner.answer_route": rag_plan.answer_route,
                    "rag.planner.route_confidence": rag_plan.route_confidence,
                    "context.mode": rag_plan.context_mode,
                    "context.selected_sources": ",".join(rag_plan.selected_sources),
                    "external_context.planned": rag_plan.should_use_external_context,
                    "external_context.hit_count": len(external_candidates),
                    "rag.planner.fallback": (
                        rag_plan.reason == RAG_PLANNER_FALLBACK_REASON
                    ),
                    "chat.prompt.tokens_input": prepared_context.assembled_prompt.total_tokens,
                    "chat.prompt.message_count": len(
                        prepared_context.assembled_prompt.messages
                    ),
                    "chat.prompt.uses_rag": prepared_context.search_context is not None,
                },
            )
            return PreparedGenerationContext(
                assembled_prompt=prepared_context.assembled_prompt,
                search_context=search_context,
                answer_model_tier=rag_plan.answer_model_tier,
                model_route_confidence=rag_plan.model_route_confidence,
                model_route_reason=rag_plan.model_route_reason,
            )

    async def build_rag_plan(
        self,
        payload: GenerationPayload,
    ) -> tuple[RAGExecutionPlan, bool]:
        default_plan = RAGExecutionPlan.from_settings(
            has_kb=payload.kb_id is not None,
            query_text=payload.query_text,
            external_context_allowed=is_external_context_allowed(
                context_mode=payload.context_mode,
                enable_external_context=payload.enable_external_context,
                external_context_enabled=payload.feature_flags.enable_external_context,
            ),
            context_mode=resolve_context_mode(
                context_mode=payload.context_mode,
                enable_external_context=payload.enable_external_context,
            ),
            infra_flags=payload.feature_flags,
        )
        if payload.rag_candidates:
            return default_plan, False
        if not payload.query_text.strip():
            return default_plan, False
        if not default_plan.selected_sources:
            return default_plan, False
        if not payload.feature_flags.enable_rag_planner:
            return default_plan, False
        if self.rag_planning_service is None:
            return default_plan, False

        try:
            plan = await self.rag_planning_service.plan(
                query_text=payload.query_text,
                conversation_history=payload.conversation_history,
                kb_id=payload.kb_id,
                enable_external_context=payload.enable_external_context,
                context_mode=payload.context_mode,
                infra_flags=payload.feature_flags,
            )
            plan = plan.clamped()
            if plan.answer_route == "refuse" and (
                not payload.feature_flags.enable_rag_planner_routing
                or plan.route_confidence
                < ai_settings.RAG_PLANNER_REFUSAL_CONFIDENCE_THRESHOLD
            ):
                return default_plan, True
            return plan, True
        except Exception as exc:
            logger.warning("Worker RAG Planner 规划失败，降级为默认计划: %s", exc)
            return default_plan, False

    def _build_planner_preflight_refusal(
        self,
        *,
        payload: GenerationPayload,
        rag_plan: RAGExecutionPlan,
    ) -> RAGEvidenceDecision | None:
        if not payload.feature_flags.enable_rag_planner_routing:
            return None
        # Preloaded RAG candidates are caller-owned context; do not let planner
        # preflight refusal discard evidence that has already been selected.
        if payload.rag_candidates:
            return None
        if rag_plan.answer_route != "refuse":
            return None
        if (
            rag_plan.route_confidence
            < ai_settings.RAG_PLANNER_REFUSAL_CONFIDENCE_THRESHOLD
        ):
            return None
        reason = (
            rag_plan.planner_refusal_reason.strip()
            or rag_plan.reason.strip()
            or "RAG planner 前置拒答"
        )
        return RAGEvidenceDecision(
            should_refuse=True,
            reason=reason,
            hit_count=0,
            policy_version=3,
        )

    async def retrieve_external_context_candidates(
        self,
        payload: GenerationPayload,
        rag_plan: RAGExecutionPlan,
    ) -> list[dict[str, Any]]:
        if (
            payload.rag_candidates
            or self.external_context_provider is None
            or not payload.feature_flags.enable_external_context
            or not source_selected(rag_plan.selected_sources, "web")
        ):
            return []

        try:
            chunks = await self.external_context_provider.search(
                query_text=payload.query_text,
                top_k=rag_plan.external_top_k,
            )
            return [
                chunk.to_rag_chunk(chunk_index=index)
                for index, chunk in enumerate(chunks)
            ]
        except Exception as exc:
            logger.warning("外部上下文检索失败，降级为仅使用 RAG: %s", exc)
            return []

    async def retrieve_rag_candidates(
        self,
        payload: GenerationPayload,
        rag_plan: RAGExecutionPlan,
    ) -> list[dict[str, Any]]:
        if payload.rag_candidates:
            return list(payload.rag_candidates)
        if (
            self.rag_service is None
            or payload.kb_id is None
            or not source_selected(rag_plan.selected_sources, "kb")
        ):
            return []

        try:
            return await self._retrieve_from_rag_service(payload, rag_plan)
        except Exception as exc:
            logger.warning("Worker RAG 候选检索失败，降级为普通对话: %s", exc)
            return []

    async def _retrieve_from_rag_service(
        self,
        payload: GenerationPayload,
        rag_plan: RAGExecutionPlan,
    ) -> list[dict[str, Any]]:
        if self.rag_service is None:
            return []
        if rag_plan.retrieval_mode == "fulltext":
            fulltext_top_k = (
                rag_plan.candidate_count if rag_plan.use_rerank else rag_plan.top_k
            )
            return await self.rag_service.retrieve_fulltext(
                query_text=payload.query_text,
                kb_id=payload.kb_id,
                top_k=fulltext_top_k,
            )
        if rag_plan.retrieval_mode == "hybrid" or rag_plan.use_rerank:
            hybrid_top_k = (
                rag_plan.candidate_count if rag_plan.use_rerank else rag_plan.top_k
            )
            return await self.rag_service.retrieve_hybrid(
                query_text=payload.query_text,
                kb_id=payload.kb_id,
                top_k=hybrid_top_k,
            )
        return await self.rag_service.retrieve(
            query_text=payload.query_text,
            kb_id=payload.kb_id,
            top_k=rag_plan.top_k,
        )

    async def rerank_candidates_if_enabled(
        self,
        payload: GenerationPayload,
        candidates: list[dict[str, Any]],
        rag_plan: RAGExecutionPlan,
    ) -> list[dict[str, Any]]:
        candidates = list(candidates)
        if not candidates:
            return []

        if not rag_plan.use_rerank:
            return candidates[: rag_plan.top_k]

        limit = max(1, rag_plan.rerank_top_k)
        if self.rag_service is None:
            return candidates[:limit]
        try:
            with trace_span(
                "taskiq.llm_stream.rerank",
                {
                    "chat.session_id": payload.session_id,
                    "rag.kb_id": payload.kb_id,
                    "rag.top_k": limit,
                    "rag.candidate_count": len(candidates),
                    "rag.planner.use_rerank": rag_plan.use_rerank,
                },
            ) as span:
                async with llm_concurrency_slot(
                    {
                        "chat.session_id": payload.session_id,
                        "rag.kb_id": payload.kb_id,
                        "rag.rerank": True,
                    }
                ):
                    reranked = await self.rag_service.rerank(
                        query_text=payload.query_text,
                        candidates=candidates,
                        top_k=limit,
                    )
                set_span_attributes(
                    span,
                    {
                        "rag.hit_count": len(reranked),
                    },
                )
                return reranked
        except Exception as exc:
            logger.warning("Worker RAG rerank 失败，降级为候选原始排序: %s", exc)
            fallback_chunks = select_rerank_fallback_candidates(candidates, limit)
            self._debug_log_final_chunks(
                payload=payload,
                chunks=fallback_chunks,
                stage="rerank_fallback_chunks",
            )
            return fallback_chunks

    def _build_refusal_search_context(
        self,
        *,
        payload: GenerationPayload,
        chunks: list[dict[str, Any]],
        decision: RAGEvidenceDecision,
    ) -> dict:
        search_context = self.chat_context_builder.build_search_context(
            kb_id=payload.kb_id,
            query_text=payload.query_text,
            rag_chunks=chunks,
        ) or {
            "version": 1,
            "kb_id": str(payload.kb_id) if payload.kb_id else None,
            "query": payload.query_text,
            "retrieval": {
                "hit_count": len(chunks),
                "source_count": 0,
                "max_score": decision.best_score or 0.0,
                "avg_score": decision.best_score or 0.0,
            },
            "refs": [],
            "chunks": [],
        }
        search_context.update(decision.to_metadata())
        return search_context

    def _build_planner_refusal_search_context(
        self,
        *,
        payload: GenerationPayload,
        decision: RAGEvidenceDecision,
        rag_plan: RAGExecutionPlan,
    ) -> dict:
        search_context = self._build_refusal_search_context(
            payload=payload,
            chunks=[],
            decision=decision,
        )
        search_context.update(
            {
                "planner_refusal": True,
                "refusal_type": "planner_preflight",
                "answer_route": rag_plan.answer_route,
                "route_confidence": rag_plan.route_confidence,
                "planner_refusal_reason": decision.reason,
            }
        )
        return search_context

    @staticmethod
    def _with_rag_metrics(
        search_context: dict | None,
        metrics: dict[str, object],
    ) -> dict | None:
        if search_context is None:
            return None
        return merge_metrics(search_context, metrics)

    @staticmethod
    def _debug_log_rag_plan(
        *,
        payload: GenerationPayload,
        rag_plan: RAGExecutionPlan,
        planner_used: bool,
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        logger.debug(
            "Worker RAG plan",
            extra={
                "chat_session_id": str(payload.session_id),
                "rag_kb_id": str(payload.kb_id) if payload.kb_id else None,
                "rag_planner_used": planner_used,
                "rag_context_mode": rag_plan.context_mode,
                "rag_selected_sources": rag_plan.selected_sources,
                "rag_should_use_rag": rag_plan.should_use_rag,
                "rag_retrieval_mode": rag_plan.retrieval_mode,
                "rag_top_k": rag_plan.top_k,
                "rag_use_rerank": rag_plan.use_rerank,
                "rag_candidate_count": rag_plan.candidate_count,
                "rag_rerank_top_k": rag_plan.rerank_top_k,
                "rag_should_use_external_context": (
                    rag_plan.should_use_external_context
                ),
                "rag_external_top_k": rag_plan.external_top_k,
                "rag_reason": rag_plan.reason,
            },
        )

    @staticmethod
    def _debug_log_final_chunks(
        *,
        payload: GenerationPayload,
        chunks: list[dict[str, Any]],
        stage: str,
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        logger.debug(
            "Worker RAG chunks",
            extra={
                "chat_session_id": str(payload.session_id),
                "rag_kb_id": str(payload.kb_id) if payload.kb_id else None,
                "rag_stage": stage,
                "rag_hit_count": len(chunks),
                "rag_hits": [_rag_chunk_debug_record(chunk) for chunk in chunks],
            },
        )


def _rag_chunk_debug_record(chunk: dict[str, Any]) -> dict[str, object]:
    return {
        "chunk_id": str(chunk.get("id")),
        "source_type": chunk.get("source_type"),
        "file_id": chunk.get("file_id"),
        "message_id": chunk.get("message_id"),
        "chunk_index": chunk.get("chunk_index"),
        "retrieval_mode": chunk.get("retrieval_mode"),
        "score_kind": chunk.get("score_kind"),
        "score": chunk.get("score"),
        "distance": chunk.get("distance"),
        "raw_score": chunk.get("raw_score"),
        "evidence_score": chunk.get("evidence_score"),
        "rerank_score": chunk.get("rerank_score"),
        "matched_by": chunk.get("matched_by"),
        "filename": chunk.get("filename"),
        "title": chunk.get("title"),
        "url": chunk.get("url"),
        "content_preview": str(chunk.get("content") or "")[:240],
    }
