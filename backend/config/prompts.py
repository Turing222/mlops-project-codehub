"""Prompt configuration loader.

职责：加载 prompt YAML，转换为 PromptResolver 使用的轻量配置对象。
边界：本模块不编译 Jinja2 模板，也不读取 Langfuse 缓存文件。
失败处理：schema 错误会转换为 ConfigurationError。
"""

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
    """单个 prompt 模板内容。"""

    content: str


@dataclass(frozen=True, slots=True)
class PromptSourceConfig:
    """Prompt 来源与缓存 fallback 设置。"""

    provider: str
    label: str
    ttl_seconds: int
    cache_path: str
    fallback: str
    synced_at: str | None = None


@dataclass(frozen=True, slots=True)
class LangfusePromptRef:
    """Langfuse prompt 引用信息。"""

    name: str
    type: str = "text"
    version: int | None = None


@dataclass(frozen=True, slots=True)
class PromptConfig:
    """Prompt 运行时配置集合。"""

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
    """从 YAML 加载并校验 prompt 配置。"""
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
    """返回进程级缓存的 prompt 配置。"""
    return load_prompt_config()
