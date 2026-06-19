"""Worker generation RAG tests — retrieval, refusal, planning, and rerank.

职责：验证 LLMGenerationWorkerWorkflow 的 RAG 检索、低分拒绝、planner 计划与 rerank 流程;边界：不启动 HTTP stack、不连接真实 Redis/LLM;副作用:无。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from backend.application.chat.stream_events import (
    encode_chunk_event,
    encode_done_event,
    encode_started_event,
)
from backend.application.chat.worker_generation_workflow import (
    LLMGenerationWorkerWorkflow,
)
from backend.models.schemas.chat.dto import LLMResultDTO
from backend.models.schemas.chat.payloads import FeatureFlags, GenerationPayload
from backend.services.rag_planning_service import RAGExecutionPlan
from tests.unit.workflows._worker_generation_helpers import (
    FakeRedis,
    FakeRedisClient,
    NonStreamingLLM,
    RecordingRAGPlanner,
    RecordingRAGService,
    StreamingLLM,
    install_llm_slot_recorder,
    make_rerank_impl,
    without_step_events,
)
from tests.unit.workflows.conftest import FakeChatUow, make_rag_hit


async def test_worker_nonstream_refuses_when_rag_has_no_hits(monkeypatch) -> None:
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = NonStreamingLLM(LLMResultDTO(content="should not run"))
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=RecordingRAGService([]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 3)
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="知识库里有什么？",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    result = await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=assistant_message_id,
        idempotency_lock_key="idempotency:test",
    )

    assert result.success is True
    assert result.content == "知识库中没有找到足够相关的信息，暂时无法基于资料回答。"
    llm_service.generate_response.assert_not_awaited()
    assert slot_calls == []
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["status"].value == "success"
    assert update_kwargs["content"] == result.content
    assert update_kwargs["search_context"]["rag_refusal"] is True
    assert update_kwargs["search_context"]["reason"] == "RAG 命中数量不足"
    assert update_kwargs["search_context"]["metrics"]["candidate_count"] == 0
    assert update_kwargs["search_context"]["metrics"]["hit_count"] == 0
    assert "retrieve_ms" in update_kwargs["search_context"]["metrics"]
    message_metadata = update_kwargs["message_metadata"]
    assert message_metadata["response_outcome"] == "refused"
    assert message_metadata["badcase"]["is_badcase"] is True
    assert message_metadata["badcase"]["severity"] == "p1"
    assert message_metadata["badcase"]["reason"] == "empty_retrieval_refusal"
    assert redis.set_calls == [("idempotency:test", str(assistant_message_id), 3600)]


async def test_worker_stream_refuses_when_rag_has_no_hits(monkeypatch) -> None:
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = StreamingLLM(["should not stream"])
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=RecordingRAGService([]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 3)

    await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="知识库里有什么？",
            conversation_history=[],
            kb_id=uuid.uuid4(),
        ),
        channel="stream:test",
        assistant_message_id=assistant_message_id,
    )

    refusal = "知识库中没有找到足够相关的信息，暂时无法基于资料回答。"
    assert without_step_events(redis.published) == [
        ("stream:test", encode_started_event()),
        ("stream:test", encode_chunk_event(refusal)),
        ("stream:test", encode_done_event()),
    ]
    assert llm_service.stream_queries == []
    assert slot_calls == []
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["content"] == refusal
    assert update_kwargs["search_context"]["rag_refusal"] is True
    assert update_kwargs["search_context"]["metrics"]["hit_count"] == 0
    assert (
        update_kwargs["message_metadata"]["badcase"]["reason"]
        == "empty_retrieval_refusal"
    )


async def test_worker_nonstream_planner_preflight_refusal_skips_llm(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = NonStreamingLLM(LLMResultDTO(content="should not run"))
    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(
        RAGExecutionPlan(
            should_use_rag=True,
            answer_route="refuse",
            route_confidence=0.9,
            planner_refusal_reason="明显无法回答",
        )
    )
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 5)

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="知识库无法回答的请求",
            conversation_history=[],
            kb_id=uuid.uuid4(),
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=True,
            ),
        ),
        assistant_message_id=uuid.uuid4(),
    )

    assert result.success is True
    assert result.content == "当前请求暂时无法可靠回答。"
    llm_service.generate_response.assert_not_awaited()
    rag_service.retrieve.assert_not_awaited()
    assert slot_calls == []
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["search_context"]["planner_refusal"] is True
    assert update_kwargs["message_metadata"]["badcase"]["reason"] == (
        "planner_preflight_refusal"
    )


async def test_worker_stream_planner_preflight_refusal_skips_llm(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = StreamingLLM(["should not stream"])
    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(
        RAGExecutionPlan(
            should_use_rag=True,
            answer_route="refuse",
            route_confidence=0.9,
            planner_refusal_reason="明显无法回答",
        )
    )
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 5)

    await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="知识库无法回答的请求",
            conversation_history=[],
            kb_id=uuid.uuid4(),
            feature_flags=FeatureFlags(
                enable_rag_planner=True,
                enable_rag_planner_routing=True,
            ),
        ),
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
    )

    assert without_step_events(redis.published) == [
        ("stream:test", encode_started_event()),
        ("stream:test", encode_chunk_event("当前请求暂时无法可靠回答。")),
        ("stream:test", encode_done_event()),
    ]
    assert llm_service.stream_queries == []
    rag_service.retrieve.assert_not_awaited()
    assert slot_calls == []
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["search_context"]["planner_refusal"] is True
    assert update_kwargs["message_metadata"]["badcase"]["reason"] == (
        "planner_preflight_refusal"
    )


async def test_worker_generation_retrieves_rag_candidates_when_kb_id_exists(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    rag_hit = make_rag_hit()
    rag_service = RecordingRAGService([rag_hit])
    llm_service = NonStreamingLLM(LLMResultDTO(content="answer"))
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=rag_service,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        feature_flags=FeatureFlags(enable_rag_rerank=False),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="hi",
        kb_id=payload.kb_id,
        top_k=4,
    )
    rag_service.retrieve_hybrid.assert_not_awaited()
    query = llm_service.generate_response.call_args.args[0]
    assert "worker-side context" in query.conversation_history[0]["content"]


async def test_worker_generation_refuses_low_vector_score(monkeypatch) -> None:
    redis = FakeRedis()

    low_hit = make_rag_hit(content="weak context", score=0.1, distance=0.9)
    llm_service = NonStreamingLLM(LLMResultDTO(content="should not run"))
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=RecordingRAGService([low_hit]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 3)

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="弱相关问题",
            conversation_history=[],
            kb_id=uuid.uuid4(),
        ),
        assistant_message_id=uuid.uuid4(),
    )

    assert result.success is True
    llm_service.generate_response.assert_not_awaited()
    assert result.search_context is not None
    assert result.search_context["reason"] == "RAG 相关性分数不足"
    assert result.search_context["best_score"] == 0.1


async def test_worker_generation_keeps_old_behavior_when_refusal_disabled(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    llm_service = NonStreamingLLM(LLMResultDTO(content="fallback answer"))
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=RecordingRAGService([]),
    )

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="知识库里有什么？",
            conversation_history=[],
            kb_id=uuid.uuid4(),
            feature_flags=FeatureFlags(enable_rag_refusal=False),
        ),
        assistant_message_id=uuid.uuid4(),
    )

    assert result.content == "fallback answer"
    llm_service.generate_response.assert_awaited_once()


async def test_worker_generation_skips_rag_when_planner_declines(monkeypatch) -> None:
    redis = FakeRedis()

    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(
        RAGExecutionPlan(
            should_use_rag=False,
            retrieval_mode="vector",
            top_k=4,
            reason="无需知识库",
        )
    )
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        feature_flags=FeatureFlags(enable_rag_planner=True),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    assert len(planner.plan_calls) == 1
    rag_service.retrieve.assert_not_awaited()
    rag_service.retrieve_fulltext.assert_not_awaited()
    rag_service.retrieve_hybrid.assert_not_awaited()


async def test_worker_generation_does_not_plan_without_kb(monkeypatch) -> None:
    redis = FakeRedis()

    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(error=AssertionError("planner should not run"))
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=None,
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    assert planner.plan_calls == []
    rag_service.retrieve.assert_not_awaited()


async def test_worker_generation_skips_planner_when_candidates_exist(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    planner = RecordingRAGPlanner(error=AssertionError("planner should not run"))
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=RecordingRAGService([]),
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        rag_candidates=[make_rag_hit(content="preloaded context")],
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    assert planner.plan_calls == []


async def test_worker_generation_uses_fulltext_plan(monkeypatch) -> None:
    redis = FakeRedis()

    rag_service = RecordingRAGService(
        [make_rag_hit(content="fulltext context", index=1)]
    )
    planner = RecordingRAGPlanner(
        RAGExecutionPlan(
            should_use_rag=True,
            retrieval_mode="fulltext",
            top_k=2,
            reason="关键词检索",
        )
    )
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="找 ctx.md",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        feature_flags=FeatureFlags(enable_rag_planner=True),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    rag_service.retrieve_fulltext.assert_awaited_once_with(
        query_text="找 ctx.md",
        kb_id=payload.kb_id,
        top_k=2,
    )
    rag_service.retrieve.assert_not_awaited()
    rag_service.retrieve_hybrid.assert_not_awaited()


async def test_worker_generation_reranks_candidates_when_enabled(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)
    monkeypatch.setattr(
        "backend.config.ai_settings.ai_settings.RAG_RERANK_TOP_K",
        1,
    )

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = StreamingLLM(["answer"])
    rag_service = RecordingRAGService([])

    rag_service.rerank = AsyncMock(side_effect=make_rerank_impl([(1, 9.0)]))
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=rag_service,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        feature_flags=FeatureFlags(enable_rag_rerank=True),
        rag_candidates=[
            {
                "id": str(uuid.uuid4()),
                "content": "low",
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "filename": "a.md",
                "chunk_index": 0,
                "meta_info": {},
                "distance": 0.3,
                "score": 0.7,
            },
            {
                "id": str(uuid.uuid4()),
                "content": "high",
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "filename": "b.md",
                "chunk_index": 1,
                "meta_info": {},
                "distance": 0.1,
                "score": 0.9,
            },
        ],
    )
    assistant_message_id = uuid.uuid4()

    await workflow.generate_stream(
        payload=payload,
        channel="stream:test",
        assistant_message_id=assistant_message_id,
    )

    rag_service.rerank.assert_awaited_once()
    stream_query = llm_service.stream_queries[0]
    system_message = stream_query.conversation_history[0]
    assert "high" in system_message["content"]
    # rerank 后 "a.md" (low content) 应被过滤
    assert "a.md" not in system_message["content"]
    assert slot_calls == [
        {
            "chat.session_id": payload.session_id,
            "rag.kb_id": payload.kb_id,
            "rag.rerank": True,
        },
        {
            "chat.session_id": payload.session_id,
            "chat.assistant_message_id": assistant_message_id,
            "chat.stream": True,
            "llm.model_tier": "balanced",
        },
    ]


async def test_worker_generation_refuses_low_rerank_score(monkeypatch) -> None:
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = StreamingLLM(["should not stream"])
    rag_service = RecordingRAGService([make_rag_hit(content="weak rerank context")])

    rag_service.rerank = AsyncMock(side_effect=make_rerank_impl([(0, 2.0)]))
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=rag_service,
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 3)

    await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
            kb_id=uuid.uuid4(),
            feature_flags=FeatureFlags(enable_rag_rerank=True),
        ),
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
    )

    rag_service.rerank.assert_awaited_once()
    assert llm_service.stream_queries == []
    assert "chat.stream" not in slot_calls[-1]
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["search_context"]["reason"] == "RAG rerank 相关性不足"
    assert update_kwargs["search_context"]["best_rerank_score"] == 2.0


async def test_worker_generation_uses_hybrid_rerank_plan(monkeypatch) -> None:
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)

    rag_service = RecordingRAGService(
        [make_rag_hit(content="low", index=0), make_rag_hit(content="high", index=1)]
    )
    planner = RecordingRAGPlanner(
        RAGExecutionPlan(
            should_use_rag=True,
            retrieval_mode="hybrid",
            top_k=2,
            use_rerank=True,
            candidate_count=8,
            rerank_top_k=1,
            reason="需要精选",
        )
    )
    llm_service = StreamingLLM(["answer"])

    rag_service.rerank = AsyncMock(side_effect=make_rerank_impl([(1, 9.0)]))
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        feature_flags=FeatureFlags(enable_rag_planner=True),
    )

    await workflow.generate_stream(
        payload=payload,
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
    )

    rag_service.retrieve_hybrid.assert_awaited_once_with(
        query_text="hi",
        kb_id=payload.kb_id,
        top_k=8,
    )
    rag_service.rerank.assert_awaited_once()
    assert "rag.rerank" in slot_calls[0]


async def test_worker_generation_uses_planner_fallback_plan(monkeypatch) -> None:
    redis = FakeRedis()

    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(
        RAGExecutionPlan.from_settings(
            has_kb=True,
            query_text="hi",
            reason="RAG planner 降级为默认计划",
        )
    )
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        feature_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_rag_rerank=False,
        ),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="hi",
        kb_id=payload.kb_id,
        top_k=4,
    )


async def test_worker_generation_uses_planner_fallback_on_exception(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(error=ValueError("LLM API failed"))
    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        feature_flags=FeatureFlags(
            enable_rag_planner=True,
            enable_rag_rerank=False,
        ),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="hi",
        kb_id=payload.kb_id,
        top_k=4,
    )
