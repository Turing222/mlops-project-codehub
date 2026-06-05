"""Google OAuth2 service.

职责：构建 Google 授权 URL、交换授权码换取令牌、解析 ID Token。
边界：本模块不处理用户查找或 JWT 签发，仅负责与 Google OAuth2 交互。
"""

import asyncio
import logging
from urllib.parse import urlencode, urlparse

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import id_token as google_id_token

from backend.core.exceptions import app_bad_request

logger = logging.getLogger(__name__)

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
_SCOPES = "openid email profile"


class GoogleOAuthService:
    """Google OAuth2 认证服务。"""

    def __init__(
        self,
        google_oauth_enabled: bool,
        google_client_id: str,
        google_client_secret: str,
        allowed_redirect_uris: list[str] | None = None,
    ) -> None:
        self._google_oauth_enabled = google_oauth_enabled
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret
        self._allowed_redirect_uris = allowed_redirect_uris or []

    def _require_enabled(self) -> None:
        if not self._google_oauth_enabled:
            raise app_bad_request("Google 登录暂未开放", code="GOOGLE_OAUTH_DISABLED")

    def _validate_redirect_uri(self, redirect_uri: str) -> str:
        """Validate redirect_uri against the whitelist."""
        if not self._allowed_redirect_uris:
            return redirect_uri
        parsed = urlparse(redirect_uri)
        origin = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        for allowed in self._allowed_redirect_uris:
            allowed_parsed = urlparse(allowed)
            allowed_origin = (
                f"{allowed_parsed.scheme}://{allowed_parsed.netloc}"
                f"{allowed_parsed.path.rstrip('/')}"
            )
            if origin == allowed_origin:
                return redirect_uri
        raise app_bad_request("redirect_uri not allowed", code="INVALID_REDIRECT_URI")

    def get_authorization_url(self, redirect_uri: str) -> str:
        """构建 Google OAuth2 授权跳转 URL。"""
        self._require_enabled()
        redirect_uri = self._validate_redirect_uri(redirect_uri)
        params = {
            "client_id": self._google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """用授权码换取 Google 令牌并解析 ID Token。

        Returns:
            包含 sub、email、name 等字段的字典。
        """
        self._require_enabled()
        redirect_uri = self._validate_redirect_uri(redirect_uri)
        async with httpx.AsyncClient(timeout=10) as client:
            # 1. 用授权码换令牌
            token_resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self._google_client_id,
                    "client_secret": self._google_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

        id_token = token_data.get("id_token")
        if not id_token:
            msg = "Google OAuth 响应中缺少 id_token"
            raise ValueError(msg)

        # 2. 本地验证 ID Token 签名、audience、issuer 与过期时间
        claims = await self._verify_id_token(id_token)
        return claims

    async def _verify_id_token(self, id_token: str) -> dict:
        """本地验证 Google ID Token 并返回核心 claims。"""
        claims = await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            id_token,
            Request(),
            self._google_client_id,
        )

        return {
            "sub": claims["sub"],
            "email": claims.get("email"),
            "name": claims.get("name"),
        }
