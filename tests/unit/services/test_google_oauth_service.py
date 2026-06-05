"""GoogleOAuthService unit tests.

职责：验证 Google OAuth URL 构造和 ID Token 本地验证映射；
边界：mock google-auth verifier，不访问 Google 网络；副作用：无。
"""

from __future__ import annotations

import pytest

from backend.core.exceptions import AppException
from backend.services.google_oauth_service import GoogleOAuthService

pytestmark = pytest.mark.asyncio


def _make_service(
    *,
    allowed_redirect_uris: list[str] | None = None,
    google_oauth_enabled: bool = True,
) -> GoogleOAuthService:
    return GoogleOAuthService(
        google_oauth_enabled=google_oauth_enabled,
        google_client_id="client-id",
        google_client_secret="client-secret",
        allowed_redirect_uris=allowed_redirect_uris,
    )


async def test_verify_id_token_uses_local_google_auth_verifier(monkeypatch) -> None:
    service = _make_service()
    calls: dict[str, object] = {}

    def fake_verify_oauth2_token(token: str, request: object, audience: str) -> dict:
        calls["token"] = token
        calls["request"] = request
        calls["audience"] = audience
        return {
            "sub": "google-sub",
            "email": "user@example.com",
            "name": "User Name",
        }

    monkeypatch.setattr(
        "backend.services.google_oauth_service.google_id_token.verify_oauth2_token",
        fake_verify_oauth2_token,
    )

    claims = await service._verify_id_token("id-token")

    assert claims == {
        "sub": "google-sub",
        "email": "user@example.com",
        "name": "User Name",
    }
    assert calls["token"] == "id-token"
    assert calls["audience"] == "client-id"


def test_get_authorization_url_rejects_disallowed_redirect_uri() -> None:
    service = _make_service(allowed_redirect_uris=["http://localhost:3000/callback"])

    with pytest.raises(AppException) as exc_info:
        service.get_authorization_url("https://evil.com/callback")

    assert exc_info.value.code == "INVALID_REDIRECT_URI"


def test_get_authorization_url_allows_whitelisted_redirect_uri() -> None:
    service = _make_service(allowed_redirect_uris=["http://localhost:3000/callback"])

    url = service.get_authorization_url("http://localhost:3000/callback")
    assert "redirect_uri=http" in url


async def test_exchange_code_rejects_disallowed_redirect_uri(monkeypatch) -> None:
    service = _make_service(allowed_redirect_uris=["http://localhost:3000/callback"])

    with pytest.raises(AppException) as exc_info:
        await service.exchange_code("some-code", "https://evil.com/callback")

    assert exc_info.value.code == "INVALID_REDIRECT_URI"


def test_get_authorization_url_allows_any_uri_when_whitelist_empty() -> None:
    service = _make_service(allowed_redirect_uris=[])

    url = service.get_authorization_url("https://any-domain.com/callback")
    assert "redirect_uri=https" in url


def test_get_authorization_url_rejects_when_google_oauth_disabled() -> None:
    service = _make_service(google_oauth_enabled=False)

    with pytest.raises(AppException) as exc_info:
        service.get_authorization_url("https://any-domain.com/callback")

    assert exc_info.value.code == "GOOGLE_OAUTH_DISABLED"
