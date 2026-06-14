"""Rerank provider factory unit tests.

职责：验证 RerankProviderFactory.create 分支逻辑；边界：monkeypatch 配置与 LLM model config；副作用：无。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ai.providers.rerank.bifrost_rerank import BifrostRerankService
from backend.ai.providers.rerank.dashscope_rerank import DashScopeRerankService
from backend.ai.providers.rerank.factory import RerankProviderFactory
from backend.config.rerank import RerankProfile


def _make_mock_config(
    base_url: str | None = "http://bifrost:8080/v1",
    api_key: str | None = "sk-test",
    rerank_profiles: dict[str, RerankProfile] | None = None,
) -> object:
    llm_profile = SimpleNamespace(
        resolve_base_url=lambda: base_url,
        resolve_api_key=lambda: api_key,
    )
    rp = rerank_profiles or {}
    alias_map: dict[str, str] = {}
    for profile_name, profile in rp.items():
        for identifier in (profile_name, *profile.aliases):
            alias_map[identifier.lower()] = profile_name

    def _resolve_rerank(name: str) -> RerankProfile | None:
        key = alias_map.get(name.strip().lower(), "")
        return rp.get(key) if key else None

    config = SimpleNamespace(
        resolve_profile=lambda _name: llm_profile,
        rerank_profiles=rp,
        rerank_alias_map=alias_map,
        resolve_rerank_profile=_resolve_rerank if alias_map else lambda _: None,
    )
    return config


def _make_rerank_profile(
    provider: str = "bifrost",
    model: str = "qwen3-rerank",
    base_url: str = "http://bifrost:8080/v1",
    api_key: str = "sk-test",
    score_kind: str | None = "bifrost_rerank",
) -> RerankProfile:
    return RerankProfile(
        name="bifrost_rerank",
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_envs=("BIFROST_API_KEY",),
        aliases=("bifrost", "bifrost-rerank", "gateway-rerank"),
        score_kind=score_kind,
    )


def _make_dashscope_rerank_profile() -> RerankProfile:
    return RerankProfile(
        name="dashscope_rerank",
        provider="dashscope",
        model="qwen3-rerank",
        base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
        api_key_envs=("DASHSCOPE_API_KEY",),
        aliases=("dashscope", "qwen3-rerank"),
        score_kind="dashscope_rerank",
    )


# ── Legacy path (no rerank profiles) ────────────────────────────


def test_create_returns_none_when_provider_is_none_and_settings_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_PROVIDER", None
    )
    assert RerankProviderFactory.create(provider=None) is None


def test_create_returns_none_when_provider_is_empty_string() -> None:
    assert RerankProviderFactory.create(provider="") is None


def test_create_returns_none_when_provider_is_whitespace() -> None:
    assert RerankProviderFactory.create(provider="  ") is None


def test_create_constructs_bifrost_service_for_bifrost_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(),
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_MODEL",
        "qwen3-rerank",
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )

    result = RerankProviderFactory.create(provider="bifrost")

    assert isinstance(result, BifrostRerankService)
    assert result.base_url == "http://bifrost:8080/v1"
    assert result.api_key == "sk-test"
    assert result.model_name == "qwen3-rerank"


def test_create_accepts_llm_gateway_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(),
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_MODEL",
        "qwen3-rerank",
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )

    result = RerankProviderFactory.create(provider="llm-gateway")
    assert isinstance(result, BifrostRerankService)


def test_create_accepts_ai_gateway_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(),
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_MODEL",
        "qwen3-rerank",
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )

    result = RerankProviderFactory.create(provider="ai-gateway")
    assert isinstance(result, BifrostRerankService)


def test_create_raises_value_error_for_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(),
    )
    with pytest.raises(ValueError, match="Unsupported RAG rerank provider"):
        RerankProviderFactory.create(provider="unknown-provider")


def test_create_raises_value_error_for_incomplete_bifrost_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(base_url=None),
    )

    with pytest.raises(ValueError, match="配置不完整"):
        RerankProviderFactory.create(provider="bifrost")


def test_create_constructs_dashscope_service_for_dashscope_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(),
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_MODEL",
        "qwen3-rerank",
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.DASHSCOPE_API_KEY",
        "sk-dashscope",
    )

    result = RerankProviderFactory.create(provider="dashscope")

    assert isinstance(result, DashScopeRerankService)
    assert result.base_url == "https://dashscope.aliyuncs.com/compatible-api/v1"
    assert result.api_key == "sk-dashscope"
    assert result.model_name == "qwen3-rerank"


# ── Profile path ─────────────────────────────────────────────────


def test_create_from_profile_constructs_bifrost_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )
    monkeypatch.setenv("BIFROST_API_KEY", "sk-profile")

    profile = _make_rerank_profile()
    result = RerankProviderFactory.create(profile=profile)

    assert isinstance(result, BifrostRerankService)
    assert result.base_url == "http://bifrost:8080/v1"
    assert result.api_key == "sk-profile"
    assert result.model_name == "qwen3-rerank"


def test_create_from_profile_constructs_dashscope_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-profile")

    profile = _make_dashscope_rerank_profile()
    result = RerankProviderFactory.create(profile=profile)

    assert isinstance(result, DashScopeRerankService)
    assert result.base_url == "https://dashscope.aliyuncs.com/compatible-api/v1"
    assert result.api_key == "sk-profile"
    assert result.model_name == "qwen3-rerank"


def test_create_from_profile_raises_for_incomplete_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BIFROST_API_KEY", raising=False)

    # Need to set api_key_envs to something that won't resolve
    profile_no_key = RerankProfile(
        name="test",
        provider="bifrost",
        model="qwen3-rerank",
        base_url=None,
        api_key_envs=("NONEXISTENT_KEY",),
        aliases=(),
        score_kind=None,
    )

    with pytest.raises(ValueError, match="配置不完整"):
        RerankProviderFactory.create(profile=profile_no_key)


def test_create_from_profile_raises_for_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIFROST_API_KEY", "sk-test")

    profile = _make_rerank_profile(provider="unsupported_provider")
    with pytest.raises(ValueError, match="Unsupported rerank provider"):
        RerankProviderFactory.create(profile=profile)


# ── Rerank profiles path (via config) ────────────────────────────


def test_create_uses_rerank_profile_when_profiles_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rerank_profile = _make_rerank_profile()
    config = _make_mock_config(
        rerank_profiles={"bifrost_rerank": rerank_profile},
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: config,
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )
    monkeypatch.setenv("BIFROST_API_KEY", "sk-via-profile")

    result = RerankProviderFactory.create(provider="bifrost")

    assert isinstance(result, BifrostRerankService)
    assert result.model_name == "qwen3-rerank"


def test_create_uses_dashscope_rerank_profile_when_profiles_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rerank_profile = _make_dashscope_rerank_profile()
    config = _make_mock_config(
        rerank_profiles={"dashscope_rerank": rerank_profile},
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: config,
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-via-profile")

    result = RerankProviderFactory.create(provider="dashscope")

    assert isinstance(result, DashScopeRerankService)
    assert result.model_name == "qwen3-rerank"
