from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.config.loader import ConfigurationError, load_yaml_config
from backend.config.schemas import LLMModelsConfig, PromptsConfig


@dataclass(frozen=True, slots=True)
class PromptTemplateConfig:
    content: str


@dataclass(frozen=True, slots=True)
class PromptSourceConfig:
    provider: str
    label: str
    ttl_seconds: int
    cache_path: str
    fallback: str
    synced_at: str | None = None


@dataclass(frozen=True, slots=True)
class LangfusePromptRef:
    name: str
    type: str = "text"
    version: int | None = None


@dataclass(frozen=True, slots=True)
class PromptConfig:
    version: int
    source: PromptSourceConfig
    langfuse_templates: dict[str, LangfusePromptRef]
    default_variables: dict[str, Any]
    templates: dict[str, PromptTemplateConfig]

    def get_template_content(self, name: str) -> str:
        try:
            return self.templates[name].content
        except KeyError as exc:
            raise ConfigurationError(f"Prompt template not found: {name}") from exc


@dataclass(frozen=True, slots=True)
class LLMProfile:
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
    name: str
    profiles: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
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
        return self.base_url or _provider_default_base_url(self.provider)


@dataclass(frozen=True, slots=True)
class LLMModelConfig:
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

    def resolve_route(self, provider_or_route: str | None = None) -> tuple[LLMProfile, ...]:
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


def load_prompt_config(
    *,
    config_dir: str | Path | None = None,
) -> PromptConfig:
    data = load_yaml_config("llm/prompts.yaml", config_dir=config_dir)
    try:
        config = PromptsConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid LLM prompts config: {exc}") from exc

    return PromptConfig(
        version=config.version,
        source=PromptSourceConfig(
            provider=config.source.provider,
            label=config.source.label,
            ttl_seconds=config.source.ttl_seconds,
            cache_path=config.source.cache_path,
            fallback=config.source.fallback,
            synced_at=config.source.synced_at,
        ),
        langfuse_templates={
            name: LangfusePromptRef(
                name=template.name,
                type=template.type,
                version=template.version,
            )
            for name, template in config.langfuse.templates.items()
        },
        default_variables=dict(config.defaults.variables),
        templates={
            name: PromptTemplateConfig(content=template.content)
            for name, template in config.templates.items()
        },
    )


def load_llm_model_config(
    *,
    config_dir: str | Path | None = None,
) -> LLMModelConfig:
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

    embedding_profiles = _build_embedding_profiles(config)
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
def get_prompt_config() -> PromptConfig:
    return load_prompt_config()


@lru_cache
def get_llm_model_config() -> LLMModelConfig:
    return load_llm_model_config()


def validate_llm_configs() -> None:
    get_prompt_config()
    get_llm_model_config()


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


def _build_embedding_profiles(config: LLMModelsConfig) -> dict[str, EmbeddingProfile]:
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


def _get_settings():
    from backend.core.config import settings

    return settings
