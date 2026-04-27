from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any

import yaml
from jinja2 import BaseLoader, Environment
from jinja2.environment import Template
from pydantic import ValidationError

from backend.config.llm import PromptConfig, load_prompt_config
from backend.config.loader import ConfigurationError
from backend.config.schemas import PromptsConfig
from backend.core.config import settings

logger = logging.getLogger(__name__)


class PromptResolver:
    """Resolve prompt templates from Langfuse cache with YAML fallback."""

    def __init__(
        self,
        *,
        prompt_config_loader: Callable[[], PromptConfig] = load_prompt_config,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.prompt_config_loader = prompt_config_loader
        self.clock = clock
        self._env = Environment(
            loader=BaseLoader(),
            autoescape=False,
            keep_trailing_newline=True,
        )
        self._lock = RLock()
        self._loaded_at = 0.0
        self._templates: dict[str, Template] = {}
        self._default_variables: dict[str, Any] = {}
        self._source = "unloaded"
        self._synced_at: str | None = None

    def get_template(self, name: str) -> Template:
        with self._lock:
            self._ensure_loaded()
            try:
                return self._templates[name]
            except KeyError as exc:
                raise ConfigurationError(f"Prompt template not found: {name}") from exc

    def get_default_variables(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            return dict(self._default_variables)

    def get_metadata(self) -> dict[str, str | None]:
        with self._lock:
            self._ensure_loaded()
            return {
                "source": self._source,
                "synced_at": self._synced_at,
            }

    def clear(self) -> None:
        with self._lock:
            self._loaded_at = 0.0
            self._templates = {}
            self._default_variables = {}
            self._source = "unloaded"
            self._synced_at = None

    def _ensure_loaded(self) -> None:
        base_config = self.prompt_config_loader()
        ttl_seconds = base_config.source.ttl_seconds
        now = self.clock()
        if self._templates and ttl_seconds > 0 and now - self._loaded_at < ttl_seconds:
            return

        config, source = self._resolve_prompt_config(base_config)
        self._templates = {
            name: self._env.from_string(template.content)
            for name, template in config.templates.items()
        }
        self._default_variables = dict(config.default_variables)
        self._source = source
        self._synced_at = config.source.synced_at
        self._loaded_at = now

    def _resolve_prompt_config(
        self,
        base_config: PromptConfig,
    ) -> tuple[PromptConfig, str]:
        if base_config.source.provider != "langfuse_cache":
            return base_config, "yaml"

        try:
            cache_config = self._load_cache_prompt_config(base_config.source.cache_path)
            return cache_config, "langfuse_cache"
        except Exception as exc:
            if base_config.source.fallback == "none":
                raise
            logger.warning(
                "Falling back to YAML prompts because Langfuse prompt cache is unavailable: %s",
                exc,
            )
            return base_config, "yaml_fallback"

    def _load_cache_prompt_config(self, cache_path: str) -> PromptConfig:
        path = _resolve_path(cache_path)
        if not path.exists():
            raise ConfigurationError(f"Prompt cache file not found: {path}")

        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Invalid YAML in prompt cache file: {path}") from exc

        try:
            config = PromptsConfig.model_validate(data)
        except ValidationError as exc:
            raise ConfigurationError(f"Invalid prompt cache config: {exc}") from exc

        return _to_prompt_config(config)


def _to_prompt_config(config: PromptsConfig) -> PromptConfig:
    from backend.config.llm import (
        LangfusePromptRef,
        PromptSourceConfig,
        PromptTemplateConfig,
    )

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


def _resolve_path(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_absolute():
        return resolved
    return settings.BASE_DIR / resolved


_prompt_resolver = PromptResolver()


def get_prompt_resolver() -> PromptResolver:
    return _prompt_resolver
