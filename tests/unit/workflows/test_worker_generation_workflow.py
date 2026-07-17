"""Worker generation workflow tests — streaming, non-streaming, guardrails, RAG, rerank.

职责：验证 LLMGenerationWorkerWorkflow 的流式/非流式生成、guardrail 拦截、RAG 检索与拒绝、
rerank 流程、concurrency slot 记录、Redis 连接轮换和幂等锁管理；
边界：不启动 HTTP stack、不连接真实 Redis/LLM/S3；副作用：无。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.application.chat.stream_events import (
    encode_chunk_event,
    encode_done_event,
    encode_error_event,
    encode_started_event,
)
from backend.application.chat.worker_generation_workflow import (
    LLMGenerationWorkerWorkflow,
)
from backend.application.chat.worker_rag_orchestrator import PreparedGenerationContext
from backend.core.exceptions import app_service_error
from backend.models.schemas.chat.dto import LLMResultDTO
from backend.models.schemas.chat.payloads import FeatureFlags, GenerationPayload
from tests.unit.workflows._worker_generation_helpers import (
    FakeRedis,
    FakeRedisClient,
    NonStreamingLLM,
    StaticRAGOrchestrator,
    StreamingLLM,
    install_llm_slot_recorder,
    without_step_events,
)
from tests.unit.workflows.conftest import FakeChatUow


async def test_worker_generation_persists_success_and_publishes_done(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    user_id = uuid.uuid4()
    updated_message = object()
    uow.chat_repo.update_message_status.return_value = updated_message

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=StreamingLLM(["hello", " world"]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 7)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
    )

    await workflow.generate_stream(
        payload=payload,
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        user_id=user_id,
        idempotency_lock_key="idempotency:test",
    )

    assert without_step_events(redis.published) == [
        ("stream:test", encode_started_event()),
        ("stream:test", encode_chunk_event("hello")),
        ("stream:test", encode_chunk_event(" world")),
        ("stream:test", encode_done_event()),
    ]
    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_id"] == assistant_message_id
    assert update_kwargs["content"] == "hello world"
    assert isinstance(update_kwargs["tokens_input"], int)
    assert update_kwargs["tokens_output"] == 7
    message_metadata = update_kwargs["message_metadata"]
    assert message_metadata["schema_version"] == 1
    assert message_metadata["response_outcome"] == "answered"
    assert message_metadata["metrics"]["tokens_output"] == 7
    assert "first_token_latency_ms" in message_metadata["metrics"]
    assert redis.set_calls == [("idempotency:test", str(assistant_message_id), 3600)]
    assert slot_calls == [
        {
            "chat.session_id": payload.session_id,
            "chat.assistant_message_id": assistant_message_id,
            "chat.stream": True,
            "llm.model_tier": "balanced",
        }
    ]


async def test_worker_generation_fetches_current_redis_connection(monkeypatch) -> None:
    old_redis = FakeRedis()
    current_redis = FakeRedis()
    redis_client = FakeRedisClient(old_redis, current_redis)
    install_llm_slot_recorder(monkeypatch)

    workflow = LLMGenerationWorkerWorkflow(
        uow=FakeChatUow(),
        redis_client=redis_client,
        llm_service=StreamingLLM(["hello"]),
    )

    await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        channel="stream:test",
    )

    assert old_redis.published == [("stream:test", encode_started_event())]
    assert without_step_events(current_redis.published) == [
        ("stream:test", encode_chunk_event("hello")),
        ("stream:test", encode_done_event()),
    ]
    assert redis_client.init_calls >= 2


async def test_worker_nonstream_uses_selected_llm_model_name(monkeypatch) -> None:
    install_llm_slot_recorder(monkeypatch)
    workflow = LLMGenerationWorkerWorkflow(
        uow=FakeChatUow(),
        redis_client=FakeRedisClient(FakeRedis()),
        llm_service=NonStreamingLLM(LLMResultDTO(content="hello", success=True)),
    )
    persist_success = AsyncMock()
    monkeypatch.setattr(
        workflow,
        "_persist_success_and_idempotency",
        persist_success,
    )

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        billing_model_name="billing-model",
    )

    result = await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    assert result.success is True
    assert persist_success.await_args.kwargs["model_name"] == "fake-model"


async def test_worker_generation_accepts_legacy_prepared_generation_tuple(
    monkeypatch,
) -> None:
    install_llm_slot_recorder(monkeypatch)
    workflow = LLMGenerationWorkerWorkflow(
        uow=FakeChatUow(),
        redis_client=FakeRedisClient(FakeRedis()),
        llm_service=NonStreamingLLM(LLMResultDTO(content="hello", success=True)),
    )

    legacy_prepared = (
        SimpleNamespace(session_id=uuid.uuid4(), query_text="hi"),
        12,
        {"metrics": {"planner_used": False}},
    )

    prepared = workflow._coerce_prepared_generation(legacy_prepared)

    assert prepared.llm_query is legacy_prepared[0]
    assert prepared.tokens_input == 12
    assert prepared.search_context == {"metrics": {"planner_used": False}}
    assert prepared.selected_llm.tier == "balanced"
    assert prepared.selected_llm.model_name == "fake-model"


async def test_worker_nonstream_routes_to_planner_model_tier(monkeypatch) -> None:
    install_llm_slot_recorder(monkeypatch)
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.LLM_MODEL_ROUTE_FAST_PROVIDER",
        "fast-provider",
    )
    default_llm = NonStreamingLLM(LLMResultDTO(content="default", success=True))
    routed_llm = NonStreamingLLM(LLMResultDTO(content="fast", success=True))
    routed_llm.provider_name = "fast"
    routed_llm.model_name = "fast-model"
    resolver_calls: list[str | None] = []

    def resolve_llm(provider: str | None):
        resolver_calls.append(provider)
        return routed_llm

    workflow = LLMGenerationWorkerWorkflow(
        uow=FakeChatUow(),
        redis_client=FakeRedisClient(FakeRedis()),
        llm_service=default_llm,
        llm_service_resolver=resolve_llm,
        rag_orchestrator=StaticRAGOrchestrator(
            PreparedGenerationContext(
                assembled_prompt=SimpleNamespace(
                    total_tokens=3,
                    messages=[{"role": "user", "content": "hi"}],
                ),
                search_context={"metrics": {"planner_used": True}},
                answer_model_tier="fast",
                model_route_confidence=0.92,
                model_route_reason="简单改写",
            )
        ),
    )

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            feature_flags=FeatureFlags(enable_llm_model_routing=True),
        ),
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    assert result.success is True
    assert result.content == "fast"
    assert resolver_calls == ["fast-provider"]
    update_kwargs = workflow.uow.chat_repo.update_message_status.await_args.kwargs
    metrics = update_kwargs["message_metadata"]["metrics"]
    assert metrics["answer_model_tier"] == "fast"
    assert metrics["answer_model_provider"] == "fast-provider"
    assert metrics["answer_model_name"] == "fast-model"
    usage_kwargs = workflow.uow.credit_repo.create_usage_record.await_args.kwargs
    assert usage_kwargs["model_name"] == "fast-model"


async def test_worker_stream_routes_to_planner_model_tier(monkeypatch) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.LLM_MODEL_ROUTE_REASONING_PROVIDER",
        "reasoning-provider",
    )
    default_llm = StreamingLLM(["default"])
    routed_llm = StreamingLLM(["reasoned"])
    routed_llm.provider_name = "reasoning"
    routed_llm.model_name = "reasoning-model"
    resolver_calls: list[str | None] = []

    def resolve_llm(provider: str | None):
        resolver_calls.append(provider)
        return routed_llm

    workflow = LLMGenerationWorkerWorkflow(
        uow=FakeChatUow(),
        redis_client=FakeRedisClient(redis),
        llm_service=default_llm,
        llm_service_resolver=resolve_llm,
        rag_orchestrator=StaticRAGOrchestrator(
            PreparedGenerationContext(
                assembled_prompt=SimpleNamespace(
                    total_tokens=3,
                    messages=[{"role": "user", "content": "hi"}],
                ),
                search_context={"metrics": {"planner_used": True}},
                answer_model_tier="reasoning",
                model_route_confidence=0.93,
                model_route_reason="复杂推理",
            )
        ),
    )

    await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            feature_flags=FeatureFlags(enable_llm_model_routing=True),
        ),
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    assert resolver_calls == ["reasoning-provider"]
    assert default_llm.stream_queries == []
    assert len(routed_llm.stream_queries) == 1
    update_kwargs = workflow.uow.chat_repo.update_message_status.await_args.kwargs
    assert update_kwargs["content"] == "reasoned"
    metrics = update_kwargs["message_metadata"]["metrics"]
    assert metrics["answer_model_tier"] == "reasoning"
    assert metrics["answer_model_provider"] == "reasoning-provider"
    assert metrics["answer_model_name"] == "reasoning-model"


async def test_worker_nonstream_falls_back_when_model_route_provider_fails(
    monkeypatch,
) -> None:
    install_llm_slot_recorder(monkeypatch)
    default_llm = NonStreamingLLM(LLMResultDTO(content="default", success=True))

    def resolve_llm(provider: str | None):
        raise RuntimeError(f"missing {provider}")

    workflow = LLMGenerationWorkerWorkflow(
        uow=FakeChatUow(),
        redis_client=FakeRedisClient(FakeRedis()),
        llm_service=default_llm,
        llm_service_resolver=resolve_llm,
        rag_orchestrator=StaticRAGOrchestrator(
            PreparedGenerationContext(
                assembled_prompt=SimpleNamespace(
                    total_tokens=3,
                    messages=[{"role": "user", "content": "hi"}],
                ),
                search_context=None,
                answer_model_tier="reasoning",
                model_route_confidence=0.95,
                model_route_reason="复杂推理",
            )
        ),
    )

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            feature_flags=FeatureFlags(enable_llm_model_routing=True),
        ),
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    assert result.success is True
    assert result.content == "default"
    update_kwargs = workflow.uow.chat_repo.update_message_status.await_args.kwargs
    metrics = update_kwargs["message_metadata"]["metrics"]
    assert metrics["answer_model_tier"] == "balanced"
    assert metrics["answer_model_provider"] == "default"
    assert metrics["model_route_fallback"] is True
    usage_kwargs = workflow.uow.credit_repo.create_usage_record.await_args.kwargs
    assert usage_kwargs["model_name"] == "fake-model"


async def test_worker_generation_marks_failed_and_publishes_error(monkeypatch) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=StreamingLLM(
            [],
            error=app_service_error("provider failed", code="LLM_FAILED"),
        ),
    )

    await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        idempotency_lock_key="idempotency:test",
    )

    assert without_step_events(redis.published) == [
        ("stream:test", encode_started_event()),
        (
            "stream:test",
            encode_error_event(
                "provider failed",
                error_code="LLM_FAILED",
                retryable=True,
            ),
        ),
        ("stream:test", encode_done_event()),
    ]
    assert redis.deleted == ["idempotency:test"]
    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_id"] == assistant_message_id
    assert update_kwargs["content"] == "provider failed"
    assert update_kwargs["message_metadata"]["response_outcome"] == "failed"


async def test_worker_stream_system_error_returns_generic_message(monkeypatch) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=StreamingLLM([], error=RuntimeError("internal secret")),
    )

    result = await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        idempotency_lock_key="idempotency:test",
    )

    assert result.success is False
    assert result.error == "服务暂时不可用，请稍后重试"
    assert without_step_events(redis.published) == [
        ("stream:test", encode_started_event()),
        (
            "stream:test",
            encode_error_event(
                "服务暂时不可用，请稍后重试",
                error_code="CHAT_GENERATION_FAILED",
                retryable=True,
            ),
        ),
        ("stream:test", encode_done_event()),
    ]
    assert redis.deleted == ["idempotency:test"]
    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_id"] == assistant_message_id
    assert update_kwargs["content"] == "服务暂时不可用，请稍后重试"
    assert update_kwargs["message_metadata"]["response_outcome"] == "failed"


async def test_worker_nonstream_generation_uses_llm_slot_and_persists_success(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    user_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = NonStreamingLLM(
        LLMResultDTO(
            content="full answer",
            prompt_tokens=12,
            completion_tokens=5,
            latency_ms=12,
        )
    )
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow, redis_client=FakeRedisClient(redis), llm_service=llm_service
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
    )

    result = await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=assistant_message_id,
        user_id=user_id,
        idempotency_lock_key="idempotency:test",
    )

    assert result.success is True
    assert result.content == "full answer"
    llm_service.generate_response.assert_awaited_once()
    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_id"] == assistant_message_id
    assert update_kwargs["content"] == "full answer"
    assert update_kwargs["tokens_input"] == 12
    assert update_kwargs["tokens_output"] == 5
    assert update_kwargs["message_metadata"]["schema_version"] == 1
    assert update_kwargs["message_metadata"]["response_outcome"] == "answered"
    metrics = update_kwargs["message_metadata"]["metrics"]
    assert metrics["tokens_input"] == 12
    assert metrics["tokens_output"] == 5
    assert metrics["tokens_input_source"] == "provider_usage"
    assert metrics["tokens_output_source"] == "provider_usage"
    create_usage_kwargs = uow.credit_repo.create_usage_record.call_args.kwargs
    assert create_usage_kwargs["model_name"] == "fake-model"
    assert create_usage_kwargs["input_tokens"] == 12
    assert create_usage_kwargs["output_tokens"] == 5
    assert redis.set_calls == [("idempotency:test", str(assistant_message_id), 3600)]
    assert slot_calls == [
        {
            "chat.session_id": payload.session_id,
            "chat.assistant_message_id": assistant_message_id,
            "chat.stream": False,
            "llm.model_tier": "balanced",
        }
    ]


async def test_worker_nonstream_falls_back_to_prepared_input_tokens(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = NonStreamingLLM(
        LLMResultDTO(content="answer", completion_tokens=5, latency_ms=12)
    )
    prepared_context = PreparedGenerationContext(
        assembled_prompt=SimpleNamespace(
            total_tokens=33,
            messages=[{"role": "user", "content": "hi"}],
        ),
        search_context=None,
    )
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_orchestrator=StaticRAGOrchestrator(prepared_context),
    )

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        assistant_message_id=assistant_message_id,
        user_id=uuid.uuid4(),
    )

    assert result.tokens_input == 33
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["tokens_input"] == 33
    assert (
        update_kwargs["message_metadata"]["metrics"]["tokens_input_source"]
        == "estimate"
    )
    assert (
        update_kwargs["message_metadata"]["metrics"]["tokens_output_source"]
        == "provider_usage"
    )


async def test_worker_nonstream_preserves_zero_provider_prompt_tokens(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = NonStreamingLLM(
        LLMResultDTO(
            content="answer",
            prompt_tokens=0,
            completion_tokens=5,
            latency_ms=12,
        )
    )
    prepared_context = PreparedGenerationContext(
        assembled_prompt=SimpleNamespace(
            total_tokens=33,
            messages=[{"role": "user", "content": "hi"}],
        ),
        search_context=None,
    )
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_orchestrator=StaticRAGOrchestrator(prepared_context),
    )

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        assistant_message_id=assistant_message_id,
        user_id=uuid.uuid4(),
    )

    assert result.tokens_input == 0
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["tokens_input"] == 0
    assert (
        update_kwargs["message_metadata"]["metrics"]["tokens_input_source"]
        == "provider_usage"
    )
    create_usage_kwargs = uow.credit_repo.create_usage_record.call_args.kwargs
    assert create_usage_kwargs["input_tokens"] == 0


async def test_worker_nonstream_falls_back_to_estimated_output_tokens(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = NonStreamingLLM(LLMResultDTO(content="answer", latency_ms=12))
    prepared_context = PreparedGenerationContext(
        assembled_prompt=SimpleNamespace(
            total_tokens=33,
            messages=[{"role": "user", "content": "hi"}],
        ),
        search_context=None,
    )
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_orchestrator=StaticRAGOrchestrator(prepared_context),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 9)

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        assistant_message_id=assistant_message_id,
        user_id=uuid.uuid4(),
    )

    assert result.tokens_output == 9
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["tokens_output"] == 9
    assert (
        update_kwargs["message_metadata"]["metrics"]["tokens_output_source"]
        == "estimate"
    )


async def test_worker_stream_timing_with_thinking_tags(monkeypatch) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=StreamingLLM(["<think>", "thinking", "</think>", "actual answer"]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 10)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
    )

    await workflow.generate_stream(
        payload=payload,
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        user_id=uuid.uuid4(),
    )

    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    metrics = update_kwargs["message_metadata"]["metrics"]
    assert "llm_thinking_ms" in metrics
    assert "llm_answer_ms" in metrics
    assert metrics["llm_thinking_ms"] >= 0
    assert metrics["llm_answer_ms"] >= 0


async def test_worker_stream_timing_without_thinking_tags(monkeypatch) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=StreamingLLM(["direct answer"]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 5)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
    )

    await workflow.generate_stream(
        payload=payload,
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        user_id=uuid.uuid4(),
    )

    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    metrics = update_kwargs["message_metadata"]["metrics"]
    assert metrics["llm_thinking_ms"] == 0
    assert metrics["llm_answer_ms"] >= 0
