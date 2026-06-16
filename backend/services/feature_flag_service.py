"""Feature flag service backed by GrowthBook CDN with local cache fallback.

职责：拉取 GrowthBook 云端规则并缓存，提供系统级/用户级灰度开关判定与封闭内测白名单校验。
边界：本模块不修改数据库，不依赖 UoW，通过 httpx 异步拉取 CDN 配置。
"""

import logging
import time
from typing import Any

import httpx
from growthbook import GrowthBook

from backend.core.circuit_breaker import CircuitBreaker
from backend.core.exceptions import AppException
from backend.models.orm.user import User

logger = logging.getLogger(__name__)

_AI_SYSTEM_FLAG_DEFAULTS: dict[str, bool] = {
    "enable-external-context": False,
    "enable-rag-rerank": False,
    "enable-rag-planner": False,
    "enable-rag-planner-routing": False,
    "enable-rag-refusal": True,
    "enable-llm-model-routing": False,
    "enable-rag-planner-thinking": False,
}


class FeatureFlagService:
    def __init__(
        self,
        *,
        growthbook_api_host: str,
        growthbook_sdk_key: str,
        app_env: str,
        beta_user_email_whitelist: set[str],
        beta_user_phone_whitelist: set[str],
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_cooldown_seconds: int = 30,
    ) -> None:
        self._growthbook_api_host = growthbook_api_host
        self._growthbook_sdk_key = growthbook_sdk_key
        self._app_env = app_env
        self._beta_user_email_whitelist = beta_user_email_whitelist
        self._beta_user_phone_whitelist = beta_user_phone_whitelist
        self._features_cache: dict[str, Any] = {}
        self._last_fetch_time: float = 0.0
        self._ttl_seconds: float = 30.0
        self._http_client: httpx.AsyncClient | None = None
        self._circuit = CircuitBreaker(
            name="growthbook",
            failure_threshold=circuit_breaker_failure_threshold,
            cooldown_seconds=circuit_breaker_cooldown_seconds,
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient()
        return self._http_client

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _ensure_features_loaded(self) -> dict[str, Any]:
        """确保 GrowthBook 规则缓存已被拉取，具备平稳超时与错误降级能力。"""
        current_time = time.time()
        if (
            not self._features_cache
            or (current_time - self._last_fetch_time) > self._ttl_seconds
        ):
            if self._growthbook_sdk_key == "sdk-dummy-key-for-development":
                return self._features_cache

            # When OPEN, skip the CDN fetch (avoid timeout wait) and keep using the local cache.
            try:
                await self._circuit.acquire()
            except AppException:
                logger.warning("GrowthBook CDN 熔断保护中，沿用本地缓存特征开关")
                return self._features_cache

            url = f"{self._growthbook_api_host}/api/features/{self._growthbook_sdk_key}"
            try:
                client = self._get_http_client()
                response = await client.get(url, timeout=3.0)
                if response.status_code == 200:
                    self._features_cache = response.json().get("features", {})
                    self._last_fetch_time = current_time
                    await self._circuit.on_success()
                    logger.info(
                        "Successfully synchronized Feature Flags from GrowthBook Cloud CDN."
                    )
                else:
                    await self._circuit.on_failure()
                    logger.warning(
                        "GrowthBook API returned non-200 status: %s",
                        response.status_code,
                    )
            except Exception as e:
                await self._circuit.on_failure()
                logger.error("Error syncing with GrowthBook Cloud CDN: %s", e)
        return self._features_cache

    async def get_system_features(self) -> dict[str, bool]:
        """获取系统级控制开关（含 AI 基础设施开关），使用 GrowthBook SDK 按环境判定。"""
        features_dict = await self._ensure_features_loaded()

        attributes = {"env": self._app_env}
        gb = GrowthBook(attributes=attributes, features=features_dict)

        result: dict[str, bool] = {
            "enable-public-registration": self._eval_flag(
                gb, "enable-public-registration", features_dict, True
            ),
            "enable-closed-beta-login": self._eval_flag(
                gb, "enable-closed-beta-login", features_dict, False
            ),
            "enable-password-login": self._eval_flag(
                gb, "enable-password-login", features_dict, False
            ),
        }

        for key, default in _AI_SYSTEM_FLAG_DEFAULTS.items():
            result[key] = self._eval_flag(gb, key, features_dict, default)

        return result

    async def get_user_features(self, user: User) -> dict[str, bool]:
        """用户级个性化标志评估，使用官方 growthbook Python SDK 本地判定。"""
        features_dict = await self._ensure_features_loaded()

        attributes = {
            "id": str(user.id),
            "username": user.username,
            "email": user.email or "",
            "is_superuser": bool(user.is_superuser),
            "is_active": bool(user.is_active),
            "env": self._app_env,
        }

        gb = GrowthBook(attributes=attributes, features=features_dict)

        return {
            "enable-pixel-avatar": self._eval_flag(
                gb, "enable-pixel-avatar", features_dict, True
            ),
            "enable-credits": self._eval_flag(
                gb, "enable-credits", features_dict, bool(user.is_superuser)
            ),
            "enable-agent-trace": self._eval_flag(
                gb, "enable-agent-trace", features_dict, bool(user.is_superuser)
            ),
        }

    @staticmethod
    def _eval_flag(
        gb: GrowthBook, key: str, features_dict: dict[str, Any], fallback: bool
    ) -> bool:
        """若云端定义了该 flag 则走 SDK 判定，否则返回代码降级默认值。"""
        return gb.is_on(key) if key in features_dict else fallback

    def is_beta_user(self, user: User) -> bool:
        """校验用户是否属于封闭内测白名单（支持仅手机号注册用户）。"""
        if user.is_superuser:
            return True
        if user.email and user.email in self._beta_user_email_whitelist:
            return True
        return bool(user.phone and user.phone in self._beta_user_phone_whitelist)
