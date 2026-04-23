from __future__ import annotations

import json

import httpx
import pytest

from tests.smoke import _http_smoke_helpers as smoke_helpers

QUERY_SENT_PATH = "/api/v1/chat/query_sent"
QUERY_STREAM_PATH = "/api/v1/chat/query_stream"

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]
SMOKE_READY_PATH = smoke_helpers.SMOKE_READY_PATH
create_auth_headers = smoke_helpers.create_auth_headers
smoke_client = smoke_helpers.smoke_client


async def _collect_sse_payloads(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    payload: dict,
) -> list[str]:
    async with client.stream(
        "POST",
        QUERY_STREAM_PATH,
        headers=headers,
        json=payload,
        timeout=30.0,
    ) as response:
        assert response.status_code == 200, await response.aread()

        payloads: list[str] = []
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue

            data = line[6:]
            payloads.append(data)
            if data == "[DONE]":
                break

    return payloads
@pytest.mark.asyncio
async def test_chat_query_sent_over_http(smoke_client: httpx.AsyncClient):
    ready_response = await smoke_client.get(SMOKE_READY_PATH)
    assert ready_response.status_code == 200, ready_response.text
    assert ready_response.json()["status"] == "ready"

    headers, suffix = await create_auth_headers(smoke_client)

    first_response = await smoke_client.post(
        QUERY_SENT_PATH,
        headers=headers,
        json={
            "query": "请确认 smoke chat 链路正常。",
            "client_request_id": f"smoke-{suffix}-1",
        },
    )

    assert first_response.status_code == 200, first_response.text
    first_body = first_response.json()
    assert first_body["session_id"]
    assert first_body["session_title"]
    assert first_body["answer"]["role"] == "assistant"
    assert first_body["answer"]["status"] == "success"
    assert first_body["answer"]["content"]

    second_response = await smoke_client.post(
        QUERY_SENT_PATH,
        headers=headers,
        json={
            "query": "请在同一个会话里再回复一次。",
            "session_id": first_body["session_id"],
            "client_request_id": f"smoke-{suffix}-2",
        },
    )

    assert second_response.status_code == 200, second_response.text
    second_body = second_response.json()
    assert second_body["session_id"] == first_body["session_id"]
    assert second_body["answer"]["role"] == "assistant"
    assert second_body["answer"]["status"] == "success"
    assert second_body["answer"]["content"]


@pytest.mark.asyncio
async def test_chat_query_stream_over_http_uses_task_worker(
    smoke_client: httpx.AsyncClient,
):
    headers, suffix = await create_auth_headers(smoke_client)
    payloads = await _collect_sse_payloads(
        smoke_client,
        headers=headers,
        payload={
            "query": "请用流式方式确认 task worker 工作正常。",
            "client_request_id": f"smoke-stream-{suffix}",
        },
    )

    assert payloads
    assert payloads[-1] == "[DONE]"

    events = [
        json.loads(item)
        for item in payloads
        if item != "[DONE]"
    ]
    meta_events = [event for event in events if event["type"] == "meta"]
    chunk_events = [event for event in events if event["type"] == "chunk"]
    error_events = [event for event in events if event["type"] == "error"]

    assert len(meta_events) == 1
    assert meta_events[0]["session_id"]
    assert meta_events[0]["session_title"]
    assert meta_events[0]["message_id"]
    assert not error_events
    assert chunk_events
    assert "".join(event["content"] for event in chunk_events).strip()
