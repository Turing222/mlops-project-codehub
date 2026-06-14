"""LLM configuration unit tests.

职责：验证 LLM、embedding 和 prompt 配置加载规则；边界：使用仓库内配置或临时目录，不访问真实模型服务；副作用：仅写入 pytest 临时目录。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.config.llm import (
    get_llm_model_config,
    load_llm_model_config,
    validate_llm_configs,
)
from backend.config.loader import ConfigurationError
from backend.config.prompts import get_prompt_config, load_prompt_config


@pytest.fixture(autouse=True)
def clear_cached_configs() -> Iterator[None]:
    get_llm_model_config.cache_clear()
    get_prompt_config.cache_clear()
    yield
    get_llm_model_config.cache_clear()
    get_prompt_config.cache_clear()


def test_load_prompt_config_reads_yaml_templates() -> None:
    config = load_prompt_config()

    assert "Dewflow" in config.default_variables["app_name"]
    assert "{{ app_name }}" in config.get_template_content("default_system")
    assert "{{ context_chunks }}" not in config.get_template_content("rag_system")
    assert "context_chunks" in config.get_template_content("rag_system")


def test_load_llm_model_config_resolves_aliases() -> None:
    config = load_llm_model_config()

    assert config.resolve_profile("mock").provider == "mock"
    assert config.resolve_profile("openai-compatible").provider == "openai-compatible"
    assert config.resolve_profile("bifrost").resolve_base_url() == (
        "http://bifrost:8080/v1"
    )
    assert config.resolve_profile("bifrost").model == "deepseek/deepseek-chat"
    assert config.resolve_profile("bifrost-reasoner").model == (
        "deepseek/deepseek-reasoner"
    )
    assert config.resolve_profile("gemini").model == "gemini-2.5-flash"
    assert [profile.model for profile in config.resolve_route("auto")] == [
        "deepseek-v4-flash",
        "gemini-2.5-flash",
    ]
    assert config.resolve_embedding_profile("google").model == "gemini-embedding-2"
    assert config.resolve_embedding_profile("google").dimensions == 768
    qwen3_embedding = config.resolve_embedding_profile("qwen3-embedding")
    assert qwen3_embedding.provider == "openai-compatible"
    assert qwen3_embedding.model == "text-embedding-v4"
    assert qwen3_embedding.resolve_base_url() == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    assert qwen3_embedding.dimensions == 768

    assert config.resolve_rerank_profile("dashscope").provider == "dashscope"
    assert config.resolve_rerank_profile("dashscope").model == "qwen3-rerank"
    assert config.resolve_rerank_profile("bifrost").provider == "bifrost"
    assert config.resolve_rerank_profile("gateway-rerank").name == "bifrost_rerank"


def test_embedding_profile_does_not_fallback_to_llm_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.config.settings.settings.LLM_BASE_URL",
        "https://api.deepseek.com",
    )
    monkeypatch.setattr(
        "backend.config.settings.settings.RAG_EMBED_BASE_URL",
        None,
    )
    config = load_llm_model_config()

    assert (
        config.resolve_embedding_profile("openai-compatible").resolve_base_url() is None
    )


def test_llm_profile_extra_body_rejects_unknown_keys(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    llm_dir = config_dir / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / "models.yaml").write_text(
        """
version: 1
default_profile: one
profiles:
  one:
    provider: mock
    model: mock
    extra_body:
      temperature: 0.7
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        load_llm_model_config(config_dir=config_dir)


def test_llm_profile_extra_body_keeps_thinking_explicit() -> None:
    config = load_llm_model_config()

    assert config.resolve_profile("deepseek-v4-flash").extra_body is None
    assert config.resolve_profile("deepseek-v4-flash-thinking").extra_body == {
        "thinking": {"type": "enabled"}
    }
    assert config.resolve_profile("bifrost_flash").extra_body is None
    assert config.resolve_profile("bifrost_flash_thinking").extra_body == {
        "thinking": {"type": "enabled"}
    }


def test_llm_profile_resolves_multiple_api_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-a, key-b;key-c\nkey-a")
    config = load_llm_model_config()

    assert config.resolve_profile("deepseek-v4-flash").resolve_api_keys() == (
        "key-a",
        "key-b",
        "key-c",
    )


def test_validate_llm_configs_accepts_provider_specific_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backend.config.settings.settings.LLM_PROVIDER", "gemini")
    monkeypatch.setattr("backend.config.settings.settings.LLM_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    validate_llm_configs()


def test_validate_llm_configs_accepts_bifrost_gateway_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backend.config.settings.settings.LLM_PROVIDER", "bifrost")
    monkeypatch.setenv("BIFROST_API_KEY", "sk-bf-test")

    validate_llm_configs()


def test_validate_llm_configs_reports_missing_bifrost_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backend.config.settings.settings.LLM_PROVIDER", "bifrost")
    monkeypatch.setattr("backend.config.settings.settings.BIFROST_API_KEY", None)
    monkeypatch.delenv("BIFROST_API_KEY", raising=False)

    with pytest.raises(ValueError, match="BIFROST_API_KEY"):
        validate_llm_configs()


def test_validate_llm_configs_reports_profile_key_envs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backend.config.settings.settings.LLM_PROVIDER", "gemini")
    monkeypatch.setattr("backend.config.settings.settings.LLM_API_KEY", "")
    monkeypatch.setattr("backend.config.settings.settings.GEMINI_API_KEY", None)
    monkeypatch.setattr("backend.config.settings.settings.GOOGLE_API_KEY", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(ValueError, match="GEMINI_API_KEY/GOOGLE_API_KEY"):
        validate_llm_configs()


def test_validate_llm_configs_reports_missing_route_profile_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backend.config.settings.settings.LLM_PROVIDER", "auto")
    monkeypatch.setattr("backend.config.settings.settings.LLM_API_KEY", "")
    monkeypatch.setattr("backend.config.settings.settings.DEEPSEEK_API_KEY", None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("backend.config.settings.settings.GEMINI_API_KEY", None)
    monkeypatch.setattr("backend.config.settings.settings.GOOGLE_API_KEY", None)

    with pytest.raises(ValueError, match="GEMINI_API_KEY/GOOGLE_API_KEY"):
        validate_llm_configs()


def test_invalid_models_config_rejects_duplicate_alias(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    llm_dir = config_dir / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / "models.yaml").write_text(
        """
version: 1
default_profile: one
profiles:
  one:
    provider: mock
    model: mock
    aliases: ["same"]
  two:
    provider: mock
    model: mock
    aliases: ["same"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        load_llm_model_config(config_dir=config_dir)


def test_invalid_prompts_config_requires_core_templates(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    llm_dir = config_dir / "llm"
    llm_dir.mkdir(parents=True)
    (llm_dir / "prompts.yaml").write_text(
        """
version: 1
templates:
  default_system:
    content: hello
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        load_prompt_config(config_dir=config_dir)
