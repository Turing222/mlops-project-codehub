"""Rerank provider factory."""

from __future__ import annotations

from backend.ai.providers.rerank.bifrost_rerank import BifrostRerankService
from backend.ai.providers.rerank.dashscope_rerank import DashScopeRerankService
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.config.rerank import RerankProfile
from backend.contracts.interfaces import AbstractRerankService

_BIFROST_COMPATIBLE_PROVIDERS = {
    "bifrost",
    "openai-compatible",
    "llm-gateway",
    "ai-gateway",
}
_DASHSCOPE_COMPATIBLE_PROVIDERS = {"dashscope", "dashscope-compatible"}


class RerankProviderFactory:
    """按配置构建 rerank 服务实例。"""

    @staticmethod
    def create(
        provider: str | None = None,
        *,
        profile: RerankProfile | None = None,
    ) -> AbstractRerankService | None:
        if profile is not None:
            return RerankProviderFactory._from_profile(profile)

        if provider is not None and not provider.strip():
            return None

        normalized = (provider or ai_settings.RAG_RERANK_PROVIDER or "").strip().lower()
        if not normalized:
            return None

        config = get_llm_model_config()
        if config.rerank_profiles:
            resolved = config.resolve_rerank_profile(normalized)
            return RerankProviderFactory._from_profile(resolved)

        if normalized in {"bifrost", "llm-gateway", "ai-gateway"}:
            llm_profile = config.resolve_profile("bifrost")
            base_url = llm_profile.resolve_base_url()
            api_key = llm_profile.resolve_api_key()
            if not base_url or not api_key:
                raise ValueError("Bifrost rerank 配置不完整，请检查 BASE_URL/API_KEY")
            return BifrostRerankService(
                base_url=base_url,
                api_key=api_key,
                model_name=ai_settings.RAG_RERANK_MODEL,
                timeout_seconds=ai_settings.RAG_RERANK_TIMEOUT_SECONDS,
            )

        if normalized in _DASHSCOPE_COMPATIBLE_PROVIDERS:
            api_key = ai_settings.DASHSCOPE_API_KEY
            if not api_key:
                raise ValueError(
                    "DashScope rerank 配置不完整，请检查 DASHSCOPE_API_KEY"
                )
            return DashScopeRerankService(
                api_key=api_key,
                model_name=ai_settings.RAG_RERANK_MODEL,
                timeout_seconds=ai_settings.RAG_RERANK_TIMEOUT_SECONDS,
            )

        raise ValueError(f"Unsupported RAG rerank provider: {provider}")

    @staticmethod
    def _from_profile(profile: RerankProfile) -> AbstractRerankService:
        base_url = profile.resolve_base_url()
        api_key = profile.resolve_api_key()
        if not base_url or not api_key:
            raise ValueError(
                f"Rerank profile {profile.name!r} 配置不完整，请检查 BASE_URL/API_KEY"
            )

        normalized = profile.provider.strip().lower()
        if normalized in _BIFROST_COMPATIBLE_PROVIDERS:
            return BifrostRerankService(
                base_url=base_url,
                api_key=api_key,
                model_name=profile.model,
                timeout_seconds=ai_settings.RAG_RERANK_TIMEOUT_SECONDS,
            )
        if normalized in _DASHSCOPE_COMPATIBLE_PROVIDERS:
            return DashScopeRerankService(
                base_url=base_url,
                api_key=api_key,
                model_name=profile.model,
                timeout_seconds=ai_settings.RAG_RERANK_TIMEOUT_SECONDS,
            )

        raise ValueError(f"Unsupported rerank provider: {profile.provider}")
