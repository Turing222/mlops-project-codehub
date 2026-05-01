from __future__ import annotations

import os
import uuid

import httpx
import pytest

SMOKE_BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:8000")
SMOKE_LIVE_PATH = os.getenv("SMOKE_LIVE_PATH", "/api/v1/health_check/live")
SMOKE_READY_PATH = os.getenv("SMOKE_READY_PATH", "/api/v1/health_check/db_ready")

REGISTER_PATH = "/api/v1/auth/register"
LOGIN_PATH = "/api/v1/auth/login"


async def ensure_live_environment(client: httpx.AsyncClient) -> None:
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
        pytest.skip(f"Smoke live endpoint returned an unexpected payload: {body!r}")


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
    suffix = uuid.uuid4().hex[:12]
    username = f"smoke_{suffix}"
    email = f"{username}@example.com"
    password = "Password123"

    await register_user(
        client,
        username=username,
        email=email,
        password=password,
    )
    token = await login_user(
        client,
        username=username,
        password=password,
    )
    return {"Authorization": f"Bearer {token}"}, suffix


@pytest.fixture
async def smoke_client():
    async with httpx.AsyncClient(
        base_url=SMOKE_BASE_URL,
        timeout=15.0,
        trust_env=False,
    ) as client:
        await ensure_live_environment(client)
        yield client
