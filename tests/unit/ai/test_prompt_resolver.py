from pathlib import Path

from backend.ai.core.prompt_resolver import PromptResolver
from backend.config.prompts import (
    LangfusePromptRef,
    PromptConfig,
    PromptSourceConfig,
    PromptTemplateConfig,
)


def make_prompt_config(
    *,
    cache_path: Path,
    fallback_content: str = "yaml {{ app_name }}",
    ttl_seconds: int = 0,
) -> PromptConfig:
    return PromptConfig(
        version=1,
        source=PromptSourceConfig(
            provider="langfuse_cache",
            label="production",
            ttl_seconds=ttl_seconds,
            cache_path=str(cache_path),
            fallback="yaml",
        ),
        langfuse_templates={
            "default_system": LangfusePromptRef(name="mlops-default-system"),
            "rag_system": LangfusePromptRef(name="mlops-rag-system"),
            "summarize": LangfusePromptRef(name="mlops-summarize"),
        },
        default_variables={"app_name": "YamlBot"},
        templates={
            "default_system": PromptTemplateConfig(content=fallback_content),
            "rag_system": PromptTemplateConfig(content="yaml rag"),
            "summarize": PromptTemplateConfig(content="yaml summarize"),
        },
    )


def write_cache(path: Path, *, content: str, app_name: str = "CacheBot") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
version: 1
source:
  provider: langfuse_cache
  label: production
  ttl_seconds: 300
  cache_path: {path}
  fallback: yaml
  synced_at: "2026-04-25T00:00:00+00:00"
langfuse:
  templates:
    default_system:
      name: mlops-default-system
      type: text
      version: 1
    rag_system:
      name: mlops-rag-system
      type: text
      version: 1
    summarize:
      name: mlops-summarize
      type: text
      version: 1
defaults:
  variables:
    app_name: {app_name}
templates:
  default_system:
    content: {content!r}
  rag_system:
    content: cache rag
  summarize:
    content: cache summarize
""",
        encoding="utf-8",
    )


def test_prompt_resolver_prefers_langfuse_cache(tmp_path: Path):
    cache_path = tmp_path / "prompts.yaml"
    write_cache(cache_path, content="cache {{ app_name }}")
    resolver = PromptResolver(
        prompt_config_loader=lambda: make_prompt_config(cache_path=cache_path)
    )

    template = resolver.get_template("default_system")

    assert template.render(**resolver.get_default_variables()) == "cache CacheBot"
    assert resolver.get_metadata()["source"] == "langfuse_cache"


def test_prompt_resolver_falls_back_to_yaml_when_cache_missing(tmp_path: Path):
    resolver = PromptResolver(
        prompt_config_loader=lambda: make_prompt_config(
            cache_path=tmp_path / "missing.yaml"
        )
    )

    template = resolver.get_template("default_system")

    assert template.render(**resolver.get_default_variables()) == "yaml YamlBot"
    assert resolver.get_metadata()["source"] == "yaml_fallback"


def test_prompt_resolver_reloads_cache_after_ttl(tmp_path: Path):
    cache_path = tmp_path / "prompts.yaml"
    write_cache(cache_path, content="cache v1")
    now = 0.0

    def clock() -> float:
        return now

    resolver = PromptResolver(
        prompt_config_loader=lambda: make_prompt_config(
            cache_path=cache_path,
            ttl_seconds=10,
        ),
        clock=clock,
    )

    assert resolver.get_template("default_system").render() == "cache v1"
    write_cache(cache_path, content="cache v2")

    now = 5.0
    assert resolver.get_template("default_system").render() == "cache v1"

    now = 11.0
    assert resolver.get_template("default_system").render() == "cache v2"
