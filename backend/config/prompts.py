from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.config.loader import ConfigurationError, load_yaml_config
from backend.config.schemas import PromptsConfig


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


@lru_cache
def get_prompt_config() -> PromptConfig:
    return load_prompt_config()
