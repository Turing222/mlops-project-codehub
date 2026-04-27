from pathlib import Path

import pytest

from backend.config.llm import load_llm_model_config, load_prompt_config
from backend.config.loader import ConfigurationError


def test_load_prompt_config_reads_yaml_templates():
    config = load_prompt_config()

    assert "Obsidian Mentor AI" in config.default_variables["app_name"]
    assert "{{ app_name }}" in config.get_template_content("default_system")
    assert "{{ context_chunks }}" not in config.get_template_content("rag_system")
    assert "context_chunks" in config.get_template_content("rag_system")


def test_load_llm_model_config_resolves_aliases():
    config = load_llm_model_config()

    assert config.resolve_profile("mock").provider == "mock"
    assert config.resolve_profile("openai-compatible").provider == "openai-compatible"
    assert config.resolve_profile("deepseek-reasoner").model == "deepseek-reasoner"
    assert config.resolve_profile("gemini").model == "gemini-2.5-flash"
    assert [profile.model for profile in config.resolve_route("auto")] == [
        "deepseek-chat",
        "deepseek-v4-flash",
        "gemini-2.5-flash",
    ]
    assert config.resolve_embedding_profile("google").model == "gemini-embedding-001"
    assert config.resolve_embedding_profile("google").dimensions == 768


def test_llm_profile_resolves_multiple_api_keys(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-a, key-b;key-c\nkey-a")
    config = load_llm_model_config()

    assert config.resolve_profile("deepseek").resolve_api_keys() == (
        "key-a",
        "key-b",
        "key-c",
    )


def test_invalid_models_config_rejects_duplicate_alias(tmp_path: Path):
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


def test_invalid_prompts_config_requires_core_templates(tmp_path: Path):
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
