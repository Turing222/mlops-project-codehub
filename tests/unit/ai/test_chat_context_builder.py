from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.ai.core.chat_context_builder import ChatContextBuilder


@pytest.mark.asyncio
async def test_build_uses_rag_prompt_and_search_context_when_chunks_found():
    kb_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    file_id = uuid.uuid4()
    rag_service = SimpleNamespace(
        retrieve=AsyncMock(
            return_value=[
                {
                    "id": str(chunk_id),
                    "content": "索引里的事实: Codex smoke RAG 正常。",
                    "source_type": "file",
                    "file_id": str(file_id),
                    "message_id": None,
                    "distance": 0.2,
                    "score": 0.8,
                }
            ]
        )
    )
    builder = ChatContextBuilder(rag_service=rag_service)
    history_messages = [
        SimpleNamespace(role="user", content="上一轮问题"),
        SimpleNamespace(role="assistant", content="上一轮回答"),
        SimpleNamespace(role="user", content="本轮问题"),
    ]

    result = await builder.build(
        history_messages=history_messages,
        current_query="本轮问题",
        kb_id=kb_id,
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="本轮问题",
        kb_id=kb_id,
    )
    system_message = result.assembled_prompt.messages[0]
    assert system_message["role"] == "system"
    assert "--- 参考资料 ---" in system_message["content"]
    assert "索引里的事实" in system_message["content"]
    assert result.assembled_prompt.messages[-1] == {
        "role": "user",
        "content": "本轮问题",
    }
    assert {
        "role": "user",
        "content": "本轮问题",
    } not in result.assembled_prompt.messages[:-1]
    assert result.search_context == {
        "kb_id": str(kb_id),
        "chunks": [
            {
                "id": str(chunk_id),
                "score": 0.8,
                "distance": 0.2,
                "source_type": "file",
                "file_id": str(file_id),
                "message_id": None,
            }
        ],
    }


@pytest.mark.asyncio
async def test_build_falls_back_to_plain_prompt_without_rag_chunks():
    kb_id = uuid.uuid4()
    rag_service = SimpleNamespace(retrieve=AsyncMock(return_value=[]))
    builder = ChatContextBuilder(rag_service=rag_service)

    result = await builder.build(
        history_messages=[],
        current_query="普通问题",
        kb_id=kb_id,
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="普通问题",
        kb_id=kb_id,
    )
    system_message = result.assembled_prompt.messages[0]
    assert "--- 参考资料 ---" not in system_message["content"]
    assert result.search_context is None


@pytest.mark.asyncio
async def test_build_falls_back_to_plain_prompt_when_rag_errors():
    rag_service = SimpleNamespace(
        retrieve=AsyncMock(side_effect=RuntimeError("vector db down"))
    )
    builder = ChatContextBuilder(rag_service=rag_service)

    result = await builder.build(
        history_messages=[],
        current_query="降级问题",
        kb_id=uuid.uuid4(),
    )

    assert result.search_context is None
    assert "--- 参考资料 ---" not in result.assembled_prompt.messages[0]["content"]
