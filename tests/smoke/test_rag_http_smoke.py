from __future__ import annotations

import asyncio
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
DEFAULT_UPLOAD_STREAM_PATH = "/api/v1/knowledge/default/upload-stream"
QUERY_SENT_PATH = "/api/v1/chat/query_sent"


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


async def _create_auth_headers(client: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    suffix = uuid.uuid4().hex[:12]
    username = f"rag_smoke_{suffix}"
    password = "Password123"

    register_response = await client.post(
        REGISTER_PATH,
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "confirm_password": password,
        },
    )
    assert register_response.status_code == 200, register_response.text

    login_response = await client.post(
        LOGIN_PATH,
        data={"username": username, "password": password},
    )
    assert login_response.status_code == 200, login_response.text
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, suffix


async def _wait_for_ingestion_ready(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    file_id: str,
    task_id: str,
) -> dict:
    file_path = f"/api/v1/knowledge/files/{file_id}"
    task_path = f"/api/v1/knowledge/tasks/{task_id}"
    deadline = asyncio.get_running_loop().time() + 45
    last_file_body: dict | None = None
    last_task_body: dict | None = None

    while asyncio.get_running_loop().time() < deadline:
        file_response = await client.get(file_path, headers=headers)
        assert file_response.status_code == 200, file_response.text
        last_file_body = file_response.json()

        task_response = await client.get(task_path, headers=headers)
        assert task_response.status_code == 200, task_response.text
        last_task_body = task_response.json()

        if (
            last_file_body["status"] == "ready"
            and last_task_body["status"] == "completed"
        ):
            return last_file_body
        if last_file_body["status"] == "failed" or last_task_body["status"] == "failed":
            pytest.fail(
                f"RAG ingestion failed: file={last_file_body!r} task={last_task_body!r}"
            )

        await asyncio.sleep(1)

    pytest.fail(
        "Timed out waiting for RAG ingestion: "
        f"file={last_file_body!r} task={last_task_body!r}"
    )


@pytest.fixture
async def smoke_client():
    async with httpx.AsyncClient(
        base_url=SMOKE_BASE_URL,
        timeout=20.0,
        trust_env=False,
    ) as client:
        await _ensure_live_environment(client)
        yield client


async def test_rag_upload_ingest_and_chat_search_context(
    smoke_client: httpx.AsyncClient,
):
    ready_response = await smoke_client.get(SMOKE_READY_PATH)
    assert ready_response.status_code == 200, ready_response.text
    assert ready_response.json()["status"] == "ready"

    headers, suffix = await _create_auth_headers(smoke_client)
    unique_fact = f"RAG_SMOKE_FACT_{suffix}"
    upload_response = await smoke_client.post(
        DEFAULT_UPLOAD_STREAM_PATH,
        headers=headers,
        files={
            "file": (
                f"rag-smoke-{suffix}.txt",
                f"{unique_fact}: compose smoke should retrieve this chunk.\n",
                "text/plain",
            )
        },
    )
    assert upload_response.status_code == 202, upload_response.text
    upload_body = upload_response.json()
    assert upload_body["file_id"]
    assert upload_body["task_id"]
    assert upload_body["kb_id"]

    await _wait_for_ingestion_ready(
        smoke_client,
        headers=headers,
        file_id=upload_body["file_id"],
        task_id=upload_body["task_id"],
    )

    chat_response = await smoke_client.post(
        QUERY_SENT_PATH,
        headers=headers,
        json={
            "query": f"请根据知识库回答 {unique_fact} 是什么。",
            "kb_id": upload_body["kb_id"],
            "client_request_id": f"rag-smoke-{suffix}",
        },
    )
    assert chat_response.status_code == 200, chat_response.text
    chat_body = chat_response.json()
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
