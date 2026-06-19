"""Chat HTTP smoke tests.

职责：验证真实 smoke 环境中的非流式与流式聊天主链路。
边界：只断言 API 可用性和关键响应字段，不做回答质量评估。
"""

from __future__ import annotations

import httpx
import pytest

from tests.smoke import _http_smoke_helpers as smoke_helpers

pytestmark = pytest.mark.smoke
create_auth_headers = smoke_helpers.create_auth_headers
smoke_client = smoke_helpers.smoke_client


async def test_chat_query_sent_over_http(smoke_client: httpx.AsyncClient):
    await smoke_helpers.ensure_ready_environment(smoke_client)

    headers, suffix = await create_auth_headers(smoke_client)
    first_body = await smoke_helpers.chat_query_sent(
        smoke_client,
        headers=headers,
        payload={
            "query": "请确认 smoke chat 链路正常。",
            "client_request_id": f"smoke-{suffix}-1",
        },
    )
    assert first_body["session_id"]
    assert first_body["session_title"]
    assert first_body["answer"]["role"] == "assistant"
    assert first_body["answer"]["status"] == "success"
    assert first_body["answer"]["content"]

    second_body = await smoke_helpers.chat_query_sent(
        smoke_client,
        headers=headers,
        payload={
            "query": "请在同一个会话里再回复一次。",
            "session_id": first_body["session_id"],
            "client_request_id": f"smoke-{suffix}-2",
        },
    )

    assert second_body["session_id"] == first_body["session_id"]
    assert second_body["answer"]["role"] == "assistant"
    assert second_body["answer"]["status"] == "success"
    assert second_body["answer"]["content"]


async def test_chat_query_stream_over_http_uses_task_worker(
    smoke_client: httpx.AsyncClient,
):
    headers, suffix = await create_auth_headers(smoke_client)
    events = await smoke_helpers.chat_query_stream_collect(
        smoke_client,
        headers=headers,
        payload={
            "query": "请用流式方式确认 task worker 工作正常。",
            "client_request_id": f"smoke-stream-{suffix}",
        },
    )

    assert events
    assert events[-1] == "[DONE]"

    typed_events = [event for event in events if isinstance(event, dict)]
    meta_events = [event for event in typed_events if event["type"] == "meta"]
    chunk_events = [event for event in typed_events if event["type"] == "chunk"]
    error_events = [event for event in typed_events if event["type"] == "error"]

    assert len(meta_events) == 1
    assert meta_events[0]["session_id"]
    assert meta_events[0]["session_title"]
    assert meta_events[0]["message_id"]
    assert not error_events
    assert chunk_events
    assert "".join(event["content"] for event in chunk_events).strip()
