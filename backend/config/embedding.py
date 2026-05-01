"""Embedding model configuration.

职责：把 LLM 模型配置中的 embeddings 段转换为运行时 profile。
边界：本模块只解析配置和环境变量，不创建 embedder 客户端。
默认值：缺少 embeddings 配置时提供 mock、google 和 openai-compatible profile。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.config.schemas import LLMModelsConfig


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    """一个可用于构建 embedder 的配置 profile。"""

    name: str
    provider: str
    model: str
    base_url: str | None
    api_key_envs: tuple[str, ...]
    aliases: tuple[str, ...]
    dimensions: int | None

    def resolve_api_key(self) -> str | None:
        settings = _get_settings()
        for env_name in self.api_key_envs:
            value = os.getenv(env_name) or getattr(settings, env_name, None)
            if value:
                return value
        return None

    def resolve_base_url(self) -> str | None:
        return self.base_url or _embedding_provider_default_base_url(self.provider)


def build_embedding_profiles(config: LLMModelsConfig) -> dict[str, EmbeddingProfile]:
    """从模型配置构建 embedding profile 映射。"""
    if config.embeddings is None:
        return {
            "mock": EmbeddingProfile(
                name="mock",
                provider="mock",
                model="mock",
                base_url=None,
                api_key_envs=(),
                aliases=("mock", "fake", "deterministic"),
                dimensions=768,
            ),
            "google": EmbeddingProfile(
                name="google",
                provider="google",
                model="gemini-embedding-001",
                base_url=None,
                api_key_envs=(
                    "RAG_EMBED_API_KEY",
                    "GEMINI_API_KEY",
                    "GOOGLE_API_KEY",
                ),
                aliases=("google", "gemini", "google-genai"),
                dimensions=768,
            ),
            "openai_compatible": EmbeddingProfile(
                name="openai_compatible",
                provider="openai-compatible",
                model="text-embedding-3-small",
                base_url=None,
                api_key_envs=("RAG_EMBED_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY"),
                aliases=("openai", "openai-compatible", "external-api"),
                dimensions=1536,
            ),
        }

    return {
        name: EmbeddingProfile(
            name=name,
            provider=profile.provider,
            model=profile.model,
            base_url=profile.base_url,
            api_key_envs=tuple(profile.api_key_envs),
            aliases=tuple(profile.aliases),
            dimensions=profile.dimensions,
        )
        for name, profile in config.embeddings.profiles.items()
    }


def _embedding_provider_default_base_url(provider: str) -> str | None:
    """Embedding provider 的默认 base URL fallback。"""
    settings = _get_settings()
    # embedding 专用 URL 优先，避免误用聊天模型的 base URL。
    if settings.RAG_EMBED_BASE_URL:
        return settings.RAG_EMBED_BASE_URL
    # openai-compatible embedding 可复用通用 LLM endpoint 作为兼容 fallback。
    normalized = provider.strip().lower()
    if normalized in {"openai", "openai-compatible"}:
        return settings.LLM_BASE_URL
    return None


def _get_settings():
    from backend.core.config import settings

    return settings
