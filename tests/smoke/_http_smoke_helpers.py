"""HTTP smoke flow helpers.

职责：集中封装真实 HTTP smoke 的认证、聊天、上传、轮询和工作空间动作。
边界：只使用 SMOKE_* 指向的运行中环境，不读取 L1 的 TEST_* 配置。
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

SMOKE_BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:8000")
SMOKE_LIVE_PATH = os.getenv("SMOKE_LIVE_PATH", "/api/v1/health_check/live")
SMOKE_READY_PATH = os.getenv("SMOKE_READY_PATH", "/api/v1/health_check/db_ready")

REGISTER_PATH = "/api/v1/auth/register"
LOGIN_PATH = "/api/v1/auth/login"
USERS_ME_PATH = "/api/v1/users/me"
WORKSPACES_PATH = "/api/v1/workspaces"
QUERY_SENT_PATH = "/api/v1/chat/query_sent"
QUERY_STREAM_PATH = "/api/v1/chat/query_stream"
CREDITS_CHECKIN_PATH = "/api/v1/credits/checkin"
DEFAULT_UPLOAD_PATH = "/api/v1/knowledge/default/upload"
KB_UPLOAD_PATH_TEMPLATE = "/api/v1/knowledge/bases/{kb_id}/upload"
TASK_STATUS_PATH_TEMPLATE = "/api/v1/knowledge/tasks/{task_id}"
FILE_STATUS_PATH_TEMPLATE = "/api/v1/knowledge/files/{file_id}"


def smoke_skip_or_fail(message: str) -> None:
    if os.getenv("SMOKE_STRICT", "false").lower() in {"1", "true", "yes", "on"}:
        pytest.fail(message)
    pytest.skip(message)


def assert_error_response(
    response: httpx.Response,
    status_code: int,
    error_code: str | None = None,
) -> dict[str, Any]:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert "error_code" in body
    assert "message" in body
    assert "request_id" in body
    if error_code is not None:
        assert body["error_code"] == error_code
    return body


async def ensure_live_environment(client: httpx.AsyncClient) -> None:
    try:
        response = await client.get(SMOKE_LIVE_PATH, timeout=2.0)
    except httpx.HTTPError as exc:
        smoke_skip_or_fail(
            f"Smoke environment is not reachable at {SMOKE_BASE_URL}: {exc}"
        )

    if response.status_code != 200:
        smoke_skip_or_fail(
            "Smoke live endpoint is unavailable: "
            f"{SMOKE_BASE_URL}{SMOKE_LIVE_PATH} -> {response.status_code}"
        )

    body = response.json()
    if body.get("status") != "alive":
        smoke_skip_or_fail(
            f"Smoke live endpoint returned an unexpected payload: {body!r}"
        )


async def ensure_ready_environment(client: httpx.AsyncClient) -> None:
    response = await client.get(SMOKE_READY_PATH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"


async def register_user(
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


async def login_user(
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


async def create_auth_headers(
    client: httpx.AsyncClient,
) -> tuple[dict[str, str], str]:
    return await auth_headers_for_new_user(client)


async def daily_checkin(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
) -> dict[str, Any]:
    response = await client.post(CREDITS_CHECKIN_PATH, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def auth_headers_for_new_user(
    client: httpx.AsyncClient,
    *,
    prefix: str = "smoke",
) -> tuple[dict[str, str], str]:
    suffix = uuid.uuid4().hex[:8]
    username = f"{prefix}_{suffix}"
    email = f"{username}@example.com"
    password = "Password123"

    await register_user(client, username=username, email=email, password=password)
    token = await login_user(client, username=username, password=password)
    headers = {"Authorization": f"Bearer {token}"}
    await daily_checkin(client, headers=headers)
    return headers, suffix


async def get_current_user(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
) -> dict[str, Any]:
    response = await client.get(USERS_ME_PATH, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"]
    assert body["is_active"] is True
    return body


async def create_workspace(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    suffix: str,
) -> dict[str, Any]:
    response = await client.post(
        WORKSPACES_PATH,
        headers=headers,
        json={"name": f"Smoke Workspace {suffix}", "slug": f"smoke-{suffix}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"]
    assert body["slug"] == f"smoke-{suffix}"
    return body


async def add_workspace_member(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    workspace_id: str,
    user_id: str,
    role: str = "member",
) -> dict[str, Any]:
    response = await client.post(
        f"{WORKSPACES_PATH}/{workspace_id}/members",
        headers=headers,
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user_id"] == user_id
    assert body["role"] == role
    return body


async def chat_query_sent(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(QUERY_SENT_PATH, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


async def chat_query_stream_collect(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> list[dict[str, Any] | str]:
    async with client.stream(
        "POST",
        QUERY_STREAM_PATH,
        headers=headers,
        json=payload,
        timeout=httpx.Timeout(30.0, read=60.0),
    ) as response:
        assert response.status_code == 200, await response.aread()

        events: list[dict[str, Any] | str] = []
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:]
            events.append("[DONE]" if data == "[DONE]" else json.loads(data))
            if data == "[DONE]":
                break
    return events


async def upload_default_knowledge_file(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    filename: str,
    content: str | bytes,
    content_type: str = "text/markdown",
) -> dict[str, Any]:
    payload = content.encode() if isinstance(content, str) else content
    response = await client.post(
        DEFAULT_UPLOAD_PATH,
        headers=headers,
        files={"file": (filename, payload, content_type)},
        timeout=30.0,
    )
    assert response.status_code == 202, response.text
    return response.json()


async def upload_knowledge_file_to_kb(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    kb_id: str,
    filename: str,
    content: str | bytes,
    content_type: str = "text/markdown",
) -> dict[str, Any]:
    payload = content.encode() if isinstance(content, str) else content
    response = await client.post(
        KB_UPLOAD_PATH_TEMPLATE.format(kb_id=kb_id),
        headers=headers,
        files={"file": (filename, payload, content_type)},
        timeout=30.0,
    )
    assert response.status_code == 202, response.text
    return response.json()


async def poll_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    headers: dict[str, str],
    is_ready: Callable[[dict[str, Any]], bool],
    timeout_seconds: float = 90.0,
    interval_seconds: float = 1.0,
) -> dict[str, Any]:
    last_response: httpx.Response | None = None
    last_body: dict[str, Any] | None = None
    attempts = max(1, int(timeout_seconds / interval_seconds))

    for _ in range(attempts):
        last_response = await client.get(path, headers=headers)
        if last_response.status_code == 200:
            last_body = last_response.json()
            if is_ready(last_body):
                return last_body
        await asyncio.sleep(interval_seconds)

    assert last_response is not None
    raise AssertionError(
        f"Timed out waiting for {path}. Last response: "
        f"{last_response.status_code} {last_body or last_response.text}"
    )


async def poll_task_completed(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    task_id: str,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    def is_terminal(body: dict[str, Any]) -> bool:
        return body.get("status") in {"completed", "failed"}

    body = await poll_json(
        client,
        TASK_STATUS_PATH_TEMPLATE.format(task_id=task_id),
        headers=headers,
        is_ready=is_terminal,
        timeout_seconds=timeout_seconds,
    )
    assert body["status"] == "completed", body
    return body


async def poll_file_ready(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    file_id: str,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    body = await poll_json(
        client,
        FILE_STATUS_PATH_TEMPLATE.format(file_id=file_id),
        headers=headers,
        is_ready=lambda payload: payload.get("status") in {"ready", "failed"},
        timeout_seconds=timeout_seconds,
    )
    assert body["status"] == "ready", body
    return body


@pytest.fixture
async def smoke_client():
    async with httpx.AsyncClient(
        base_url=SMOKE_BASE_URL,
        timeout=15.0,
        trust_env=False,
    ) as client:
        await ensure_live_environment(client)
        yield client
