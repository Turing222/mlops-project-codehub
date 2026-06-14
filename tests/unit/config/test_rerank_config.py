"""Rerank profile configuration unit tests.

职责：验证 RerankProfile dataclass、build_rerank_profiles 和 RerankModelsConfig schema。
边界：monkeypatch settings 与环境变量；副作用：无。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.config.rerank import RerankProfile, build_rerank_profiles
from backend.config.schemas.reranks import RerankModelProfile, RerankModelsConfig


def _make_config(reranks_data: dict | None) -> SimpleNamespace:
    if reranks_data is None:
        return SimpleNamespace(reranks=None)
    schema = RerankModelsConfig.model_validate(reranks_data)
    return SimpleNamespace(reranks=schema)


class TestRerankProfile:
    def test_resolve_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        profile = RerankProfile(
            name="test",
            provider="bifrost",
            model="qwen3-rerank",
            base_url="http://bifrost:8080/v1",
            api_key_envs=("BIFROST_API_KEY",),
            aliases=(),
            score_kind=None,
        )
        monkeypatch.setenv("BIFROST_API_KEY", "sk-from-env")
        assert profile.resolve_api_key() == "sk-from-env"

    def test_resolve_api_key_fallback_to_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile = RerankProfile(
            name="test",
            provider="bifrost",
            model="qwen3-rerank",
            base_url="http://bifrost:8080/v1",
            api_key_envs=("BIFROST_API_KEY",),
            aliases=(),
            score_kind=None,
        )
        monkeypatch.delenv("BIFROST_API_KEY", raising=False)
        fake_settings = SimpleNamespace(BIFROST_API_KEY="sk-from-settings")
        monkeypatch.setattr(
            "backend.config.rerank._get_settings", lambda: fake_settings
        )
        assert profile.resolve_api_key() == "sk-from-settings"

    def test_resolve_api_key_returns_none_when_empty(self) -> None:
        profile = RerankProfile(
            name="test",
            provider="bifrost",
            model="qwen3-rerank",
            base_url="http://bifrost:8080/v1",
            api_key_envs=("NONEXISTENT_KEY",),
            aliases=(),
            score_kind=None,
        )
        assert profile.resolve_api_key() is None

    def test_resolve_base_url_uses_profile_value(self) -> None:
        profile = RerankProfile(
            name="test",
            provider="bifrost",
            model="qwen3-rerank",
            base_url="http://custom:8080/v1",
            api_key_envs=(),
            aliases=(),
            score_kind=None,
        )
        assert profile.resolve_base_url() == "http://custom:8080/v1"

    def test_resolve_base_url_falls_back_to_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile = RerankProfile(
            name="test",
            provider="bifrost",
            model="qwen3-rerank",
            base_url=None,
            api_key_envs=(),
            aliases=(),
            score_kind=None,
        )
        fake_settings = SimpleNamespace(RAG_RERANK_BASE_URL="http://fallback:8080/v1")
        monkeypatch.setattr(
            "backend.config.rerank._get_settings", lambda: fake_settings
        )
        assert profile.resolve_base_url() == "http://fallback:8080/v1"

    def test_effective_score_kind_from_profile(self) -> None:
        profile = RerankProfile(
            name="test",
            provider="bifrost",
            model="qwen3-rerank",
            base_url=None,
            api_key_envs=(),
            aliases=(),
            score_kind="custom_score",
        )
        assert profile.effective_score_kind() == "custom_score"

    def test_effective_score_kind_default(self) -> None:
        profile = RerankProfile(
            name="test",
            provider="bifrost",
            model="qwen3-rerank",
            base_url=None,
            api_key_envs=(),
            aliases=(),
            score_kind=None,
        )
        assert profile.effective_score_kind() == "bifrost_rerank"

    def test_from_schema(self) -> None:
        schema = RerankModelProfile(
            provider="bifrost",
            model="qwen3-rerank",
            base_url="http://bifrost:8080/v1",
            api_key_envs=["BIFROST_API_KEY"],
            aliases=["bifrost-rerank"],
            score_kind="bifrost_rerank",
        )
        profile = RerankProfile.from_schema("bifrost_rerank", schema)
        assert profile.name == "bifrost_rerank"
        assert profile.provider == "bifrost"
        assert profile.model == "qwen3-rerank"
        assert profile.base_url == "http://bifrost:8080/v1"
        assert profile.api_key_envs == ("BIFROST_API_KEY",)
        assert profile.aliases == ("bifrost-rerank",)
        assert profile.score_kind == "bifrost_rerank"


class TestBuildRerankProfiles:
    def test_returns_empty_when_reranks_is_none(self) -> None:
        config = _make_config(None)
        assert build_rerank_profiles(config) == {}

    def test_builds_profiles_from_schema(self) -> None:
        config = _make_config(
            {
                "default_profile": "dashscope_rerank",
                "profiles": {
                    "dashscope_rerank": {
                        "provider": "dashscope",
                        "model": "qwen3-rerank",
                        "base_url": "https://dashscope.aliyuncs.com/compatible-api/v1",
                        "api_key_envs": ["DASHSCOPE_API_KEY"],
                        "aliases": ["dashscope", "qwen3-rerank"],
                        "score_kind": "dashscope_rerank",
                    },
                    "bifrost_rerank": {
                        "provider": "bifrost",
                        "model": "qwen3-rerank",
                        "base_url": "http://bifrost:8080/v1",
                        "api_key_envs": ["BIFROST_API_KEY"],
                        "aliases": ["bifrost", "gateway-rerank"],
                        "score_kind": "bifrost_rerank",
                    },
                },
            }
        )
        profiles = build_rerank_profiles(config)
        assert "dashscope_rerank" in profiles
        assert profiles["dashscope_rerank"].provider == "dashscope"
        assert profiles["dashscope_rerank"].api_key_envs == ("DASHSCOPE_API_KEY",)
        assert "bifrost_rerank" in profiles
        assert profiles["bifrost_rerank"].provider == "bifrost"
        assert profiles["bifrost_rerank"].model == "qwen3-rerank"


class TestRerankModelsConfig:
    def test_valid_config(self) -> None:
        config = RerankModelsConfig.model_validate(
            {
                "default_profile": "dashscope_rerank",
                "profiles": {
                    "dashscope_rerank": {
                        "provider": "dashscope",
                        "model": "qwen3-rerank",
                        "base_url": "https://dashscope.aliyuncs.com/compatible-api/v1",
                        "api_key_envs": ["DASHSCOPE_API_KEY"],
                        "aliases": ["dashscope"],
                        "score_kind": "dashscope_rerank",
                    },
                    "bifrost_rerank": {
                        "provider": "bifrost",
                        "model": "qwen3-rerank",
                        "base_url": "http://bifrost:8080/v1",
                        "api_key_envs": ["BIFROST_API_KEY"],
                        "aliases": ["bifrost-rerank"],
                        "score_kind": "bifrost_rerank",
                    },
                },
            }
        )
        assert config.default_profile == "dashscope_rerank"

    def test_rejects_missing_default_profile(self) -> None:
        with pytest.raises(Exception, match="not defined"):
            RerankModelsConfig.model_validate(
                {
                    "default_profile": "nonexistent",
                    "profiles": {
                        "bifrost_rerank": {
                            "provider": "bifrost",
                            "model": "qwen3-rerank",
                        },
                    },
                }
            )

    def test_rejects_alias_conflict(self) -> None:
        with pytest.raises(Exception, match="used by both"):
            RerankModelsConfig.model_validate(
                {
                    "default_profile": "a",
                    "profiles": {
                        "a": {
                            "provider": "bifrost",
                            "model": "model-a",
                            "aliases": ["shared-alias"],
                        },
                        "b": {
                            "provider": "cohere",
                            "model": "model-b",
                            "aliases": ["shared-alias"],
                        },
                    },
                }
            )
