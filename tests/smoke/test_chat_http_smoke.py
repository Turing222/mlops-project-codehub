from __future__ import annotations

import json
import os
import uuid

import httpx
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]

SMOKE_BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:8000")
SMOKE_LIVE_PATH = os.getenv("SMOKE_LIVE_PATH", "/api/v1/health_check/live")
SMOKE_READY_PATH = os.getenv("SMOKE_READY_PATH", "/api/v1/health_check/db_ready")

REGISTER_PATH = "/api/v1/auth/register"
LOGIN_PATH = "/api/v1/auth/login"
QUERY_SENT_PATH = "/api/v1/chat/query_sent"
QUERY_STREAM_PATH = "/api/v1/chat/query_stream"


async def _ensure_live_environment(client: httpx.AsyncClient) -> None:
    try:
        response = await client.get(SMOKE_LIVE_PATH, timeout=2.0)
    except httpx.HTTPError as exc:
        pytest.skip(f"Smoke environment is not reachable at {SMOKE_BASE_URL}: {exc}")

    if response.status_code != 200:
        pytest.skip(
            "Smoke live endpoint is unavailable: "
            f"{SMOKE_BASE_URL}{SMOKE_LIVE_PATH} -> {response.status_code}"
        )

    body = response.json()
    if body.get("status") != "alive":
        pytest.skip(
            "Smoke live endpoint returned an unexpected payload: "
            f"{body!r}"
        )


async def _register_user(
    client: httpx.AsyncClient,
    *,
    username: str,
    email: str,
    password: str,
) -> None:
    response = await client.post(
        REGISTER_PATH,
        json={
            "username": username,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["username"] == username
    assert body["email"] == email


async def _login_user(
    client: httpx.AsyncClient,
    *,
    username: str,
    password: str,
) -> str:
    response = await client.post(
        LOGIN_PATH,
        data={"username": username, "password": password},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    token = body["access_token"]
    assert token
    return token


async def _create_auth_headers(client: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    suffix = uuid.uuid4().hex[:12]
    username = f"smoke_{suffix}"
    email = f"{username}@example.com"
    password = "Password123"

    await _register_user(
        client,
        username=username,
        email=email,
        password=password,
    )
    token = await _login_user(
        client,
        username=username,
        password=password,
    )
    return {"Authorization": f"Bearer {token}"}, suffix


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


@pytest.fixture
async def smoke_client():
    async with httpx.AsyncClient(
        base_url=SMOKE_BASE_URL,
        timeout=15.0,
        trust_env=False,
    ) as client:
        await _ensure_live_environment(client)
        yield client


@pytest.mark.asyncio
async def test_chat_query_sent_over_http(smoke_client: httpx.AsyncClient):
    ready_response = await smoke_client.get(SMOKE_READY_PATH)
    assert ready_response.status_code == 200, ready_response.text
    assert ready_response.json()["status"] == "ready"

    headers, suffix = await _create_auth_headers(smoke_client)

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
    headers, suffix = await _create_auth_headers(smoke_client)
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
