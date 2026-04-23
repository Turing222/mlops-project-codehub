from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models.orm.knowledge import KnowledgeBase
from tests.smoke import _http_smoke_helpers as smoke_helpers

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]
SMOKE_READY_PATH = smoke_helpers.SMOKE_READY_PATH
create_auth_headers = smoke_helpers.create_auth_headers
smoke_client = smoke_helpers.smoke_client

USERS_ME_PATH = "/api/v1/users/me"
UPLOAD_STREAM_PATH_TEMPLATE = "/api/v1/knowledge/bases/{kb_id}/upload-stream"
TASK_STATUS_PATH_TEMPLATE = "/api/v1/knowledge/tasks/{task_id}"
FILE_STATUS_PATH_TEMPLATE = "/api/v1/knowledge/files/{file_id}"


def _smoke_database_url() -> str | None:
    explicit_url = os.getenv("SMOKE_DATABASE_URL")
    if explicit_url:
        return explicit_url

    pg_host = os.getenv("POSTGRES_SERVER")
    pg_password = os.getenv("POSTGRES_PASSWORD")
    if not pg_host or not pg_password:
        return None

    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB", "mentor_ai")
    return (
        f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"
    )


async def _resolve_or_create_kb_id(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    suffix: str,
) -> str:
    existing_kb_id = os.getenv("SMOKE_KB_ID")
    if existing_kb_id:
        return existing_kb_id

    db_url = _smoke_database_url()
    if not db_url:
        pytest.skip(
            "Knowledge smoke test requires SMOKE_KB_ID or a DB connection via "
            "SMOKE_DATABASE_URL / POSTGRES_* env vars."
        )

    me_response = await client.get(USERS_ME_PATH, headers=headers)
    assert me_response.status_code == 200, me_response.text
    user_id = me_response.json()["id"]

    kb = KnowledgeBase(
        name=f"smoke_kb_{suffix}",
        description="Knowledge upload smoke test",
        user_id=uuid.UUID(user_id),
    )

    engine = create_async_engine(db_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        async with session_factory() as session:
            session.add(kb)
            await session.commit()
            await session.refresh(kb)
    except Exception as exc:
        await engine.dispose()
        pytest.skip(
            "Knowledge smoke test could not seed a knowledge base. "
            "Set SMOKE_KB_ID to reuse an existing KB or provide a reachable "
            f"database via SMOKE_DATABASE_URL. Error: {exc}"
        )
    await engine.dispose()
    return str(kb.id)


async def _poll_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    headers: dict[str, str],
    is_ready: Callable[[dict], bool] | None = None,
    timeout_seconds: float = 90.0,
    interval_seconds: float = 1.0,
) -> dict:
    last_response: httpx.Response | None = None
    last_body: dict | None = None
    attempts = max(1, int(timeout_seconds / interval_seconds))

    for _ in range(attempts):
        last_response = await client.get(path, headers=headers)
        if last_response.status_code == 200:
            last_body = last_response.json()
            if is_ready is None or is_ready(last_body):
                return last_body
        await asyncio.sleep(interval_seconds)

    assert last_response is not None
    raise AssertionError(
        f"Timed out waiting for {path}. Last response: "
        f"{last_response.status_code} {last_body or last_response.text}"
    )


@pytest.mark.asyncio
async def test_knowledge_upload_stream_over_http_reaches_ready_state(
    smoke_client: httpx.AsyncClient,
):
    ready_response = await smoke_client.get(SMOKE_READY_PATH)
    assert ready_response.status_code == 200, ready_response.text
    assert ready_response.json()["status"] == "ready"

    headers, suffix = await create_auth_headers(smoke_client)
    kb_id = await _resolve_or_create_kb_id(
        smoke_client,
        headers=headers,
        suffix=suffix,
    )

    upload_response = await smoke_client.post(
        UPLOAD_STREAM_PATH_TEMPLATE.format(kb_id=kb_id),
        headers=headers,
        files={
            "file": (
                f"smoke_{suffix}.txt",
                f"Smoke knowledge upload {suffix}\nThis file proves task worker ingestion.\n".encode(),
                "text/plain",
            )
        },
        timeout=30.0,
    )

    assert upload_response.status_code == 202, upload_response.text
    upload_body = upload_response.json()
    assert upload_body["task_id"]
    assert upload_body["file_id"]
    assert upload_body["file_status"] == "uploaded"
    assert upload_body["task_status"] == "pending"

    task_id = upload_body["task_id"]
    file_id = upload_body["file_id"]

    task_body = None
    for _ in range(90):
        task_response = await smoke_client.get(
            TASK_STATUS_PATH_TEMPLATE.format(task_id=task_id),
            headers=headers,
        )
        assert task_response.status_code == 200, task_response.text
        task_body = task_response.json()
        if task_body["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(1.0)

    assert task_body is not None
    assert task_body["status"] == "completed", task_body
    assert task_body["progress"] == 100, task_body

    file_body = await _poll_json(
        smoke_client,
        FILE_STATUS_PATH_TEMPLATE.format(file_id=file_id),
        headers=headers,
        is_ready=lambda body: body.get("status") == "ready",
    )
    assert file_body["kb_id"] == kb_id
    assert file_body["status"] == "ready", file_body
    assert file_body["filename"].endswith(".txt")
    assert file_body["file_size"] > 0
