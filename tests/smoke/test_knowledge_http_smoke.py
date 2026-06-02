"""Knowledge HTTP smoke tests.

职责：验证真实 smoke 环境中的知识库上传、任务完成、文件状态和 chunk 入库。
边界：允许读取 smoke DB 做索引校验，不承担 RAG 回答质量评估。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models.orm.knowledge import KnowledgeBase
from tests.smoke import _http_smoke_helpers as smoke_helpers

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]
create_auth_headers = smoke_helpers.create_auth_headers
smoke_client = smoke_helpers.smoke_client

USERS_ME_PATH = "/api/v1/users/me"


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
    pg_db = _read_smoke_env_value("POSTGRES_DB") or "dewflow"
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
        smoke_helpers.smoke_skip_or_fail(
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
        smoke_helpers.smoke_skip_or_fail(
            "Knowledge smoke test could not seed a knowledge base. "
            "Set SMOKE_KB_ID to reuse an existing KB or provide a reachable "
            f"database via SMOKE_DATABASE_URL. Error: {exc}"
        )
    await engine.dispose()
    return str(kb.id)


def _build_chunking_probe_document(suffix: str) -> str:
    paragraphs = []
    for index in range(1, 6):
        marker = f"CHUNK_SPLIT_PROBE_{suffix}_{index}"
        sentence = (
            f"{marker} proves paragraph {index} survived worker chunking and "
            "database indexing with deterministic searchable content. "
        )
        paragraphs.append(sentence * 10)
    return "\n\n".join(paragraphs)


async def _fetch_file_chunks(file_id: str) -> list[dict]:
    db_url = _smoke_database_url()
    if not db_url:
        smoke_helpers.smoke_skip_or_fail(
            "Chunk DB verification requires SMOKE_DATABASE_URL or POSTGRES_* env vars."
        )

    engine = create_async_engine(db_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT
                        id::text AS id,
                        content,
                        token_count,
                        chunk_index,
                        chunking_version,
                        meta_info,
                        vector_dims(embedding) AS embedding_dim
                    FROM document_chunks
                    WHERE file_id = :file_id
                    ORDER BY chunk_index ASC
                    """
                ),
                {"file_id": file_id},
            )
            return [dict(row._mapping) for row in result]
    finally:
        await engine.dispose()


async def _fetch_file_storage_record(file_id: str) -> dict[str, Any] | None:
    db_url = _smoke_database_url()
    if not db_url:
        return None

    engine = create_async_engine(db_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT
                        file_path,
                        storage_backend,
                        storage_bucket,
                        storage_key
                    FROM knowledge_files
                    WHERE id = :file_id
                    """
                ),
                {"file_id": uuid.UUID(file_id)},
            )
            row = result.fetchone()
            return dict(row._mapping) if row else None
    finally:
        await engine.dispose()


def _host_s3_endpoint_url() -> str:
    endpoint = _read_smoke_env_value("S3_ENDPOINT_URL")
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.hostname == "minio":
            port = _read_smoke_env_value("MINIO_API_PORT") or str(parsed.port or 9000)
            return urlunparse(parsed._replace(netloc=f"localhost:{port}"))
        return endpoint
    return f"http://localhost:{_read_smoke_env_value('MINIO_API_PORT') or '9000'}"


def _read_s3_text_object(*, bucket: str, key: str) -> str:
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=_host_s3_endpoint_url(),
        region_name=_read_smoke_env_value("S3_REGION") or "us-east-1",
        aws_access_key_id=_read_smoke_env_value("S3_ACCESS_KEY_ID") or "minioadmin",
        aws_secret_access_key=(
            _read_smoke_env_value("S3_SECRET_ACCESS_KEY") or "minioadmin"
        ),
    )
    response = client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def _storage_backend_is_s3() -> bool:
    return (_read_smoke_env_value("STORAGE_BACKEND") or "local").lower() == "s3"


async def test_host_s3_endpoint_url_maps_minio_to_host_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://minio:9000/minio-path")
    monkeypatch.setenv("MINIO_API_PORT", "19000")

    assert _host_s3_endpoint_url() == "http://localhost:19000/minio-path"


@pytest.mark.asyncio
async def test_knowledge_upload_over_http_reaches_ready_state(
    smoke_client: httpx.AsyncClient,
):
    await smoke_helpers.ensure_ready_environment(smoke_client)

    headers, suffix = await create_auth_headers(smoke_client)
    kb_id = await _resolve_or_create_kb_id(
        smoke_client,
        headers=headers,
        suffix=suffix,
    )

    probe_document = _build_chunking_probe_document(suffix)
    upload_body = await smoke_helpers.upload_knowledge_file_to_kb(
        smoke_client,
        headers=headers,
        kb_id=kb_id,
        filename=f"smoke_{suffix}.md",
        content=probe_document,
    )

    assert upload_body["task_id"]
    assert upload_body["file_id"]
    assert upload_body["file_status"] == "uploaded"
    assert upload_body["task_status"] == "pending"

    task_id = upload_body["task_id"]
    file_id = upload_body["file_id"]

    task_body = await smoke_helpers.poll_task_completed(
        smoke_client,
        headers=headers,
        task_id=task_id,
    )
    assert task_body["progress"] == 100, task_body

    file_body = await smoke_helpers.poll_file_ready(
        smoke_client,
        headers=headers,
        file_id=file_id,
    )
    assert file_body["kb_id"] == kb_id
    assert file_body["filename"].endswith(".md")
    assert file_body["file_size"] > 0

    chunks = await _fetch_file_chunks(file_id)
    assert len(chunks) >= 2
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk["chunking_version"] == 2 for chunk in chunks)
    assert all(chunk["token_count"] > 0 for chunk in chunks)
    assert all(chunk["embedding_dim"] == 768 for chunk in chunks)
    assert all(
        chunk["meta_info"]["filename"] == f"smoke_{suffix}.md" for chunk in chunks
    )
    storage_record = await _fetch_file_storage_record(file_id)
    assert storage_record is not None
    db_file_path = storage_record["file_path"]
    assert db_file_path is not None
    assert all(chunk["meta_info"]["path"] == db_file_path for chunk in chunks)

    if _storage_backend_is_s3():
        assert storage_record["storage_backend"] == "s3"
        assert storage_record["storage_bucket"]
        assert storage_record["storage_key"]
        assert storage_record["file_path"] == (
            f"s3://{storage_record['storage_bucket']}/{storage_record['storage_key']}"
        )
        stored_text = _read_s3_text_object(
            bucket=storage_record["storage_bucket"],
            key=storage_record["storage_key"],
        )
        assert f"CHUNK_SPLIT_PROBE_{suffix}_1" in stored_text

    indexed_text = "\n".join(chunk["content"] for chunk in chunks)
    for index in range(1, 6):
        assert f"CHUNK_SPLIT_PROBE_{suffix}_{index}" in indexed_text

    other_headers, _other_suffix = await create_auth_headers(smoke_client)
    file_denied_response = await smoke_client.get(
        f"/api/v1/knowledge/files/{file_id}",
        headers=other_headers,
    )
    smoke_helpers.assert_error_response(
        file_denied_response,
        404,
        "KNOWLEDGE_BASE_NOT_FOUND",
    )

    task_denied_response = await smoke_client.get(
        f"/api/v1/knowledge/tasks/{task_id}",
        headers=other_headers,
    )
    smoke_helpers.assert_error_response(task_denied_response, 404, "TASK_NOT_FOUND")


@pytest.mark.asyncio
async def test_knowledge_upload_rejects_invalid_requests_over_http(
    smoke_client: httpx.AsyncClient,
):
    await smoke_helpers.ensure_ready_environment(smoke_client)

    headers, _suffix = await create_auth_headers(smoke_client)
    unsupported_response = await smoke_client.post(
        "/api/v1/knowledge/default/upload",
        headers=headers,
        files={"file": ("smoke.txt", b"not markdown", "text/plain")},
        timeout=30.0,
    )
    smoke_helpers.assert_error_response(
        unsupported_response,
        422,
        "KNOWLEDGE_FILE_UNSUPPORTED_TYPE",
    )

    missing_file_response = await smoke_client.post(
        "/api/v1/knowledge/default/upload",
        headers=headers,
        files={"other": ("smoke.md", b"# missing field", "text/markdown")},
        timeout=30.0,
    )
    smoke_helpers.assert_error_response(
        missing_file_response,
        422,
        "REQUEST_VALIDATION_ERROR",
    )
