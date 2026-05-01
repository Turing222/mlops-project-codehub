"""LLM model configuration.

职责：加载 LLM、路由和 embedding profile 配置，并解析 provider/profile alias。
边界：本模块只读取 YAML 与环境变量，不创建具体 provider 客户端。
失败处理：未知 profile、route 或 embedding provider 会抛出配置错误。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from backend.config.embedding import EmbeddingProfile, build_embedding_profiles
from backend.config.loader import ConfigurationError, load_yaml_config
from backend.config.prompts import get_prompt_config
from backend.config.schemas import LLMModelsConfig


@dataclass(frozen=True, slots=True)
class LLMProfile:
    """一个可实例化 LLM provider 的配置 profile。"""

    name: str
    provider: str
    model: str
    base_url: str | None
    api_key_envs: tuple[str, ...]
    aliases: tuple[str, ...]

    def resolve_api_key(self) -> str | None:
        api_keys = self.resolve_api_keys()
        return api_keys[0] if api_keys else None

    def resolve_api_keys(self) -> tuple[str, ...]:
        settings = _get_settings()
        api_keys: list[str] = []
        for env_name in self.api_key_envs:
            value = os.getenv(env_name) or getattr(settings, env_name, None)
            if value:
                api_keys.extend(_split_api_key_value(value))
        return tuple(dict.fromkeys(api_keys))

    def resolve_base_url(self) -> str | None:
        return self.base_url or _provider_default_base_url(self.provider)


@dataclass(frozen=True, slots=True)
class LLMRoute:
    """一组按顺序 fallback 的 LLM profile。"""

    name: str
    profiles: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LLMModelConfig:
    """LLM 与 embedding 运行时配置索引。"""

    default_profile: str
    profiles: dict[str, LLMProfile]
    alias_map: dict[str, str]
    routes: dict[str, LLMRoute]
    route_alias_map: dict[str, str]
    embedding_default_profile: str
    embedding_profiles: dict[str, EmbeddingProfile]
    embedding_alias_map: dict[str, str]

    def resolve_profile(self, provider_or_profile: str | None = None) -> LLMProfile:
        settings = _get_settings()
        raw_identifier = (
            provider_or_profile or settings.LLM_PROVIDER or self.default_profile
        )
        identifier = raw_identifier.strip().lower()
        profile_name = self.alias_map.get(identifier)
        if profile_name is None:
            raise ConfigurationError(
                f"Unsupported LLM provider/profile: {raw_identifier}"
            )
        return self.profiles[profile_name]

    def resolve_route(
        self, provider_or_route: str | None = None
    ) -> tuple[LLMProfile, ...]:
        settings = _get_settings()
        raw_identifier = (
            provider_or_route or settings.LLM_PROVIDER or self.default_profile
        )
        identifier = raw_identifier.strip().lower()
        route_name = self.route_alias_map.get(identifier)
        if route_name is None:
            return (self.resolve_profile(raw_identifier),)

        route = self.routes[route_name]
        return tuple(self.profiles[profile_name] for profile_name in route.profiles)

    def resolve_embedding_profile(
        self,
        provider_or_profile: str | None = None,
    ) -> EmbeddingProfile:
        settings = _get_settings()
        raw_identifier = (
            provider_or_profile
            or getattr(settings, "RAG_EMBED_PROVIDER", None)
            or self.embedding_default_profile
        )
        identifier = raw_identifier.strip().lower()
        profile_name = self.embedding_alias_map.get(identifier)
        if profile_name is None:
            raise ConfigurationError(
                f"Unsupported embedding provider/profile: {raw_identifier}"
            )
        return self.embedding_profiles[profile_name]


def load_llm_model_config(
    *,
    config_dir: str | Path | None = None,
) -> LLMModelConfig:
    """从 YAML 加载并校验 LLM 模型配置。"""
    data = load_yaml_config("llm/models.yaml", config_dir=config_dir)
    try:
        config = LLMModelsConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid LLM models config: {exc}") from exc

    profiles = {
        name: LLMProfile(
            name=name,
            provider=profile.provider,
            model=profile.model,
            base_url=profile.base_url,
            api_key_envs=tuple(profile.api_key_envs),
            aliases=tuple(profile.aliases),
        )
        for name, profile in config.profiles.items()
    }
    alias_map: dict[str, str] = {}
    for profile_name, profile in profiles.items():
        for identifier in (profile_name, *profile.aliases):
            alias_map[identifier.lower()] = profile_name

    routes = {
        name: LLMRoute(
            name=name,
            profiles=tuple(route.profiles),
            aliases=tuple(route.aliases),
        )
        for name, route in config.routes.items()
    }
    route_alias_map: dict[str, str] = {}
    for route_name, route in routes.items():
        for identifier in (route_name, *route.aliases):
            route_alias_map[identifier.lower()] = route_name

    embedding_profiles = build_embedding_profiles(config)
    embedding_alias_map: dict[str, str] = {}
    for profile_name, profile in embedding_profiles.items():
        for identifier in (profile_name, *profile.aliases):
            embedding_alias_map[identifier.lower()] = profile_name

    return LLMModelConfig(
        default_profile=config.default_profile,
        profiles=profiles,
        alias_map=alias_map,
        routes=routes,
        route_alias_map=route_alias_map,
        embedding_default_profile=(
            config.embeddings.default_profile if config.embeddings else "mock"
        ),
        embedding_profiles=embedding_profiles,
        embedding_alias_map=embedding_alias_map,
    )


@lru_cache
def get_llm_model_config() -> LLMModelConfig:
    """返回进程级缓存的 LLM 模型配置。"""
    return load_llm_model_config()


def validate_llm_configs() -> None:
    """启动时校验 prompt 和模型配置能被加载。"""
    get_prompt_config()
    get_llm_model_config()
    s = _get_settings()
    if s.LLM_PROVIDER.strip().lower() != "mock" and not s.LLM_API_KEY:
        raise ValueError(
            f"LLM_PROVIDER='{s.LLM_PROVIDER}' 要求设置 LLM_API_KEY，当前为空。"
        )


def _provider_default_base_url(provider: str) -> str | None:
    settings = _get_settings()
    normalized = provider.strip().lower()
    if normalized == "deepseek":
        return settings.DEEPSEEK_BASE_URL
    if normalized in {"openai", "openai-compatible"}:
        return settings.LLM_BASE_URL
    return None


def _split_api_key_value(value: str) -> list[str]:
    separators = (",", ";", "\n")
    parts = [value]
    for separator in separators:
        parts = [piece for part in parts for piece in part.split(separator)]
    return [part.strip() for part in parts if part.strip()]


def _get_settings():
    from backend.config.settings import settings

    return settings
