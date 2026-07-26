"""Payload limit middleware unit tests.

职责：验证请求体大小限制、跳过规则和 JSON body replay；边界：使用 ASGITransport 进程内请求，不访问真实网络；副作用：无。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.middleware.payload_limit import PayloadLimitMiddleware


@pytest.fixture
async def payload_client() -> AsyncIterator[AsyncClient]:
    inner_app = FastAPI()

    @inner_app.post("/echo-size")
    async def echo_size(request: Request) -> dict[str, int | str]:
        body = await request.body()
        return {"size": len(body), "body": body.decode("utf-8")}

    @inner_app.get("/echo-get")
    async def echo_get() -> dict[str, bool]:
        return {"ok": True}

    app = PayloadLimitMiddleware(inner_app, max_payload_size=5)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _chunked_large_body() -> AsyncIterator[bytes]:
    yield b"abc"
    yield b"def"


async def test_rejects_large_json_body_while_streaming(
    payload_client: AsyncClient,
) -> None:
    response = await payload_client.post(
        "/echo-size",
        content=_chunked_large_body(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Payload Too Large"}


async def test_replays_json_body_when_size_equals_limit(
    payload_client: AsyncClient,
) -> None:
    response = await payload_client.post(
        "/echo-size",
        content=b"hello",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"size": 5, "body": "hello"}


async def test_json_body_replay_delegates_subsequent_receive() -> None:
    seen_messages: list[dict[str, object]] = []
    receive_messages = [
        {"type": "http.request", "body": b"hello", "more_body": False},
        {"type": "http.disconnect"},
    ]

    async def receive() -> dict[str, object]:
        return receive_messages.pop(0)

    async def send(_message: dict[str, object]) -> None:
        return None

    async def inner_app(scope, receive, send) -> None:
        seen_messages.append(await receive())
        seen_messages.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = PayloadLimitMiddleware(inner_app, max_payload_size=5)
    await app(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
        send,
    )

    assert seen_messages == [
        {"type": "http.request", "body": b"hello", "more_body": False},
        {"type": "http.disconnect"},
    ]


async def test_skips_get_requests_returns_200(payload_client: AsyncClient) -> None:
    response = await payload_client.get("/echo-get")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_skips_multipart_body_buffering_never_returns_413(
    payload_client: AsyncClient,
) -> None:
    response = await payload_client.post(
        "/echo-size",
        content=b"ok",
        headers={"Content-Type": "multipart/form-data; boundary=---boundary"},
    )

    # Multipart upload size is enforced outside this middleware, so this path
    # must not reject solely because buffering was skipped.
    assert response.status_code != 413


async def test_rejects_large_non_json_body_when_content_length_is_known(
    payload_client: AsyncClient,
) -> None:
    response = await payload_client.post(
        "/echo-size",
        content=b"abcdef",
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Payload Too Large"}


async def test_skips_chunked_non_json_without_content_length_passes_through(
    payload_client: AsyncClient,
) -> None:
    response = await payload_client.post(
        "/echo-size",
        content=_chunked_large_body(),
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 200
    assert response.json()["size"] == 6
