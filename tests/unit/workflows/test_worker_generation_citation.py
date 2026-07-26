"""Worker generation citation tests — invalid marker removal and skip paths.

职责：验证 LLMGenerationWorkerWorkflow 的引用标记校验、非法标记移除与跳过路径;边界：不启动 HTTP stack、不连接真实 Redis/LLM;副作用:无。
"""

from __future__ import annotations

import uuid

from backend.application.chat.stream_events import (
    decode_stream_event,
)
from backend.application.chat.worker_generation_workflow import (
    LLMGenerationWorkerWorkflow,
)
from backend.models.schemas.chat.dto import LLMQueryDTO, LLMResultDTO
from backend.models.schemas.chat.payloads import GenerationPayload
from tests.unit.workflows._worker_generation_helpers import (
    FakeRedis,
    FakeRedisClient,
    NonStreamingLLM,
    StreamingLLM,
    install_llm_slot_recorder,
)
from tests.unit.workflows.conftest import FakeChatUow


def _make_search_context_with_refs() -> dict:
    """Build a search_context dict with R1 (2 chunks) and R2 (1 chunk)."""
    return {
        "version": 1,
        "kb_id": str(uuid.uuid4()),
        "query": "test query",
        "retrieval": {
            "hit_count": 3,
            "source_count": 2,
            "max_score": 0.9,
            "avg_score": 0.8,
        },
        "refs": [
            {
                "ref_id": "R1",
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "filename": "doc1.md",
                "chunks": [
                    {
                        "ref_id": "R1.1",
                        "chunk_id": str(uuid.uuid4()),
                        "chunk_index": 0,
                        "score": 0.9,
                        "distance": 0.1,
                        "meta_info": {},
                    },
                    {
                        "ref_id": "R1.2",
                        "chunk_id": str(uuid.uuid4()),
                        "chunk_index": 1,
                        "score": 0.8,
                        "distance": 0.2,
                        "meta_info": {},
                    },
                ],
            },
            {
                "ref_id": "R2",
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "filename": "doc2.md",
                "chunks": [
                    {
                        "ref_id": "R2.1",
                        "chunk_id": str(uuid.uuid4()),
                        "chunk_index": 0,
                        "score": 0.7,
                        "distance": 0.3,
                        "meta_info": {},
                    },
                ],
            },
        ],
        "chunks": [
            {
                "ref_id": "R1.1",
                "id": str(uuid.uuid4()),
                "score": 0.9,
                "distance": 0.1,
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "chunk_index": 0,
            },
            {
                "ref_id": "R1.2",
                "id": str(uuid.uuid4()),
                "score": 0.8,
                "distance": 0.2,
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "chunk_index": 1,
            },
            {
                "ref_id": "R2.1",
                "id": str(uuid.uuid4()),
                "score": 0.7,
                "distance": 0.3,
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "chunk_index": 0,
            },
        ],
    }


async def test_worker_nonstream_citation_removes_invalid_markers(monkeypatch) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    uow.user_repo.try_increment_used_tokens_with_limit.return_value = True
    llm_service = NonStreamingLLM(
        LLMResultDTO(
            content="text [R1.1] more [R9.1] end", completion_tokens=10, latency_ms=50
        )
    )
    search_context = _make_search_context_with_refs()

    async def fake_prepare(self, payload, *, on_step=None):

        dto = LLMQueryDTO(
            session_id=payload.session_id,
            query_text=payload.query_text,
            conversation_history=[],
        )
        return dto, 20, search_context

    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.LLMGenerationWorkerWorkflow._prepare_generation",
        fake_prepare,
    )

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 8)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )
    assistant_message_id = uuid.uuid4()

    result = await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=assistant_message_id,
        user_id=uuid.uuid4(),
        idempotency_lock_key="idempotency:test",
    )

    assert result.success is True
    assert result.content == "text [R1.1] more  end"
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["content"] == "text [R1.1] more  end"
    metadata = update_kwargs["message_metadata"]
    assert metadata["citation"]["total"] == 2
    assert metadata["citation"]["removed_count"] == 1
    assert "citation_validate_ms" in update_kwargs["search_context"]["metrics"]


async def test_worker_stream_citation_removes_invalid_markers(monkeypatch) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    uow.user_repo.try_increment_used_tokens_with_limit.return_value = True
    llm_service = StreamingLLM(["text [R1.1] ", "more [R9.1] end"])
    search_context = _make_search_context_with_refs()

    async def fake_prepare(self, payload, *, on_step=None):

        dto = LLMQueryDTO(
            session_id=payload.session_id,
            query_text=payload.query_text,
            conversation_history=[],
        )
        return dto, 20, search_context

    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.LLMGenerationWorkerWorkflow._prepare_generation",
        fake_prepare,
    )

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 8)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )
    assistant_message_id = uuid.uuid4()

    await workflow.generate_stream(
        payload=payload,
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        user_id=uuid.uuid4(),
        idempotency_lock_key="idempotency:test",
    )

    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["content"] == "text [R1.1] more  end"
    metadata = update_kwargs["message_metadata"]
    assert metadata["citation"]["total"] == 2
    assert metadata["citation"]["removed_count"] == 1
    assert "citation_validate_ms" in update_kwargs["search_context"]["metrics"]

    # Verify published chunks contain no invalid markers

    chunk_events = []
    for channel_name, payload in redis.published:
        if channel_name == "stream:test":
            event = decode_stream_event(payload)
            if event.get("type") == "chunk":
                chunk_events.append(event.get("content", ""))
    combined_stream = "".join(chunk_events)
    assert "[R9.1]" not in combined_stream
    assert "[R1.1]" in combined_stream


async def test_worker_citation_skips_when_no_search_context(monkeypatch) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    uow.user_repo.try_increment_used_tokens_with_limit.return_value = True
    llm_service = NonStreamingLLM(
        LLMResultDTO(
            content="no citations here [R1.1]", completion_tokens=5, latency_ms=10
        )
    )

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 5)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
    )
    assistant_message_id = uuid.uuid4()

    result = await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=assistant_message_id,
        user_id=uuid.uuid4(),
        idempotency_lock_key="idempotency:test",
    )

    assert result.success is True
    assert result.content == "no citations here [R1.1]"
    metadata = uow.chat_repo.update_message_status.call_args.kwargs["message_metadata"]
    assert "citation" not in metadata


async def test_worker_citation_skips_when_guardrail_blocked(monkeypatch) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    unsafe_output = "用户密码是 secret123"
    llm_service = NonStreamingLLM(LLMResultDTO(content=unsafe_output))
    search_context = _make_search_context_with_refs()

    async def fake_prepare(self, payload, *, on_step=None):

        dto = LLMQueryDTO(
            session_id=payload.session_id,
            query_text=payload.query_text,
            conversation_history=[],
        )
        return dto, 20, search_context

    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.LLMGenerationWorkerWorkflow._prepare_generation",
        fake_prepare,
    )

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 6)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    result = await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=uuid.uuid4(),
    )

    assert result.content == "抱歉，这个请求涉及安全或权限风险，暂时无法回答。"
    metadata = uow.chat_repo.update_message_status.call_args.kwargs["message_metadata"]
    assert metadata["guardrail"]["output"]["triggered"] is True
    assert "citation" not in metadata


async def test_worker_citation_records_zero_when_no_markers_in_output(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)

    uow = FakeChatUow()
    uow.chat_repo.update_message_status.return_value = object()
    uow.user_repo.try_increment_used_tokens_with_limit.return_value = True
    llm_service = NonStreamingLLM(
        LLMResultDTO(
            content="plain answer with no citations", completion_tokens=8, latency_ms=30
        )
    )
    search_context = _make_search_context_with_refs()

    async def fake_prepare(self, payload, *, on_step=None):

        dto = LLMQueryDTO(
            session_id=payload.session_id,
            query_text=payload.query_text,
            conversation_history=[],
        )
        return dto, 20, search_context

    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.LLMGenerationWorkerWorkflow._prepare_generation",
        fake_prepare,
    )

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        redis_client=FakeRedisClient(redis),
        llm_service=llm_service,
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 8)

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    result = await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        idempotency_lock_key="idempotency:test",
    )

    assert result.success is True
    assert result.content == "plain answer with no citations"
    metadata = uow.chat_repo.update_message_status.call_args.kwargs["message_metadata"]
    assert metadata["citation"]["total"] == 0
    assert metadata["citation"]["removed_count"] == 0
