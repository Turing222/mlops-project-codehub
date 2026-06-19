"""RAG HTTP smoke tests.

职责：验证真实 smoke 环境中上传、摄取、检索上下文和聊天回答链路。
边界：只检查可用性和引用结构，质量评分留给 evals。
"""

from __future__ import annotations

import httpx
import pytest

from tests.smoke import _http_smoke_helpers as smoke_helpers

pytestmark = pytest.mark.smoke
smoke_client = smoke_helpers.smoke_client


async def test_rag_upload_ingest_and_chat_search_context(
    smoke_client: httpx.AsyncClient,
):
    await smoke_helpers.ensure_ready_environment(smoke_client)

    headers, suffix = await smoke_helpers.auth_headers_for_new_user(
        smoke_client,
        prefix="rag_smoke",
    )
    unique_fact = f"RAG_SMOKE_FACT_{suffix}"
    upload_body = await smoke_helpers.upload_default_knowledge_file(
        smoke_client,
        headers=headers,
        filename=f"rag-smoke-{suffix}.md",
        content=f"# Smoke Fact\n\n{unique_fact}: compose smoke should retrieve this chunk.\n",
    )
    assert upload_body["file_id"]
    assert upload_body["task_id"]
    assert upload_body["kb_id"]

    await smoke_helpers.poll_task_completed(
        smoke_client,
        headers=headers,
        task_id=upload_body["task_id"],
        timeout_seconds=45.0,
    )
    await smoke_helpers.poll_file_ready(
        smoke_client,
        headers=headers,
        file_id=upload_body["file_id"],
        timeout_seconds=45.0,
    )

    chat_body = await smoke_helpers.chat_query_sent(
        smoke_client,
        headers=headers,
        payload={
            "query": f"请根据知识库回答 {unique_fact} 是什么。",
            "kb_id": upload_body["kb_id"],
            "client_request_id": f"rag-smoke-{suffix}",
        },
    )
    answer = chat_body["answer"]
    assert answer["status"] == "success"
    assert answer["content"]

    search_context = answer["search_context"]
    assert search_context is not None
    assert search_context["kb_id"] == upload_body["kb_id"]
    assert search_context["refs"]
    assert search_context["chunks"]
    first_ref = search_context["refs"][0]
    assert first_ref["source_type"] == "file"
    assert first_ref["file_id"] == upload_body["file_id"]
    assert first_ref["chunks"][0]["ref_id"].startswith("R")
    assert first_ref["chunks"][0]["chunk_id"]
    first_chunk = search_context["chunks"][0]
    assert first_chunk["source_type"] == "file"
    assert first_chunk["file_id"] == upload_body["file_id"]
    assert first_chunk["ref_id"] == first_ref["chunks"][0]["ref_id"]
    assert first_chunk["id"]
