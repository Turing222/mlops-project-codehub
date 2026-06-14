"""Rerank model configuration.

职责：把 LLM 模型配置中的 reranks 段转换为运行时 profile。
边界：本模块只解析配置和环境变量，不创建 rerank 客户端。
默认值：缺少 reranks 配置时返回空 profile 映射（rerank 是可选功能）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.config.schemas.reranks import (
    RerankModelProfile as _SchemaRerankProfile,
)

if TYPE_CHECKING:
    from backend.config.schemas import LLMModelsConfig


@dataclass(frozen=True, slots=True)
class RerankProfile:
    """一个可用于构建 rerank 服务的配置 profile。"""

    name: str
    provider: str
    model: str
    base_url: str | None
    api_key_envs: tuple[str, ...]
    aliases: tuple[str, ...]
    score_kind: str | None

    def resolve_api_key(self) -> str | None:
        settings = _get_settings()
        for env_name in self.api_key_envs:
            value = os.getenv(env_name) or getattr(settings, env_name, None)
            if value:
                return value
        return None

    def resolve_base_url(self) -> str | None:
        settings = _get_settings()
        return self.base_url or getattr(settings, "RAG_RERANK_BASE_URL", None)

    def effective_score_kind(self) -> str:
        return self.score_kind or f"{self.provider}_rerank"

    @classmethod
    def from_schema(cls, name: str, profile: _SchemaRerankProfile) -> RerankProfile:
        return cls(
            name=name,
            provider=profile.provider,
            model=profile.model,
            base_url=profile.base_url,
            api_key_envs=tuple(profile.api_key_envs),
            aliases=tuple(profile.aliases),
            score_kind=profile.score_kind,
        )


def build_rerank_profiles(config: LLMModelsConfig) -> dict[str, RerankProfile]:
    """从模型配置构建 rerank profile 映射。缺少 reranks 段时返回空 dict。"""
    if config.reranks is None:
        return {}

    return {
        name: RerankProfile.from_schema(name, profile)
        for name, profile in config.reranks.profiles.items()
    }


def _get_settings():
    from backend.config.settings import settings

    return settings
