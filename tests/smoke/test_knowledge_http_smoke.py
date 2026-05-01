from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models.orm.knowledge import KnowledgeBase
from tests.smoke import _http_smoke_helpers as smoke_helpers

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]
SMOKE_READY_PATH = smoke_helpers.SMOKE_READY_PATH
create_auth_headers = smoke_helpers.create_auth_headers
smoke_client = smoke_helpers.smoke_client

USERS_ME_PATH = "/api/v1/users/me"
UPLOAD_PATH_TEMPLATE = "/api/v1/knowledge/bases/{kb_id}/upload"
TASK_STATUS_PATH_TEMPLATE = "/api/v1/knowledge/tasks/{task_id}"
FILE_STATUS_PATH_TEMPLATE = "/api/v1/knowledge/files/{file_id}"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _smoke_env_file() -> Path:
    configured = os.getenv("SMOKE_ENV_FILE", ".env.smoke")
    path = Path(configured)
    if not path.is_absolute():
        path = _project_root() / path
    return path


def _read_smoke_env_value(name: str) -> str | None:
    if value := os.getenv(name):
        return value

    env_file = _smoke_env_file()
    if not env_file.is_file():
        return None

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == name:
            return value.strip().strip("\"'")
    return None


def _read_secret_value(path: str) -> str | None:
    secret_path = Path(path)
    if not secret_path.is_absolute():
        secret_path = _project_root() / secret_path
    if not secret_path.is_file():
        return None
    return secret_path.read_text(encoding="utf-8").strip()


def _smoke_database_url() -> str | None:
    explicit_url = os.getenv("SMOKE_DATABASE_URL")
    if explicit_url:
        return explicit_url

    pg_password = os.getenv("POSTGRES_PASSWORD")
    if not pg_password:
        secret_file = (
            _read_smoke_env_value("SMOKE_POSTGRES_PASSWORD_FILE")
            or "./secrets/smoke/postgres_password.txt"
        )
        pg_password = _read_secret_value(secret_file)

    if not pg_password:
        return None

    pg_host = os.getenv("SMOKE_POSTGRES_HOST", "localhost")
    pg_user = _read_smoke_env_value("POSTGRES_USER") or "postgres"
    pg_port = int(_read_smoke_env_value("POSTGRES_PORT") or "5432")
    pg_db = _read_smoke_env_value("POSTGRES_DB") or "mentor_ai"
    return URL.create(
        "postgresql+asyncpg",
        username=pg_user,
        password=pg_password,
        host=pg_host,
        port=pg_port,
        database=pg_db,
    ).render_as_string(hide_password=False)


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
    session_factory = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
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
async def test_knowledge_upload_over_http_reaches_ready_state(
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
        UPLOAD_PATH_TEMPLATE.format(kb_id=kb_id),
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
