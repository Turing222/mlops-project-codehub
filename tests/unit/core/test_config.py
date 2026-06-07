"""Core configuration unit tests.

职责：验证 settings 加载、环境覆盖和配置检查规则；边界：使用 monkeypatch 与临时配置目录，不读取开发者私有配置；副作用：修改进程环境并由 pytest 恢复。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend.config.settings import Settings
from backend.config.web_settings import DEFAULT_SECRET_KEY, get_web_settings
from backend.core.secret_env import load_secret_env
from scripts.qa.config_check import run_checks

TEST_SECRET_KEY = "test-secret-key-with-at-least-32-chars"
PROD_SECRET_KEY = "prod-secret-key-with-at-least-32-chars"


def test_settings_can_load_without_explicit_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.SECRET_KEY == DEFAULT_SECRET_KEY


def test_backend_log_level_defaults_to_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BACKEND_LOG_LEVEL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.BACKEND_LOG_LEVEL == "info"


def test_backend_log_level_loads_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BACKEND_LOG_LEVEL", "debug")

    settings = Settings(_env_file=None)

    assert settings.BACKEND_LOG_LEVEL == "debug"


def test_growthbook_sdk_key_loads_from_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "growthbook_sdk_key.txt"
    secret_file.write_text("sdk-secret-from-file\n", encoding="utf-8")
    monkeypatch.delenv("GROWTHBOOK_SDK_KEY", raising=False)
    monkeypatch.setenv("GROWTHBOOK_SDK_KEY_FILE", str(secret_file))

    load_secret_env()

    settings = Settings(_env_file=None)

    assert settings.GROWTHBOOK_SDK_KEY == "sdk-secret-from-file"


def test_github_token_loads_from_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "github_token.txt"
    secret_file.write_text("github-token-from-file\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN_FILE", str(secret_file))

    load_secret_env()

    settings = Settings(_env_file=None)

    assert settings.GITHUB_TOKEN == "github-token-from-file"


def test_google_client_secret_loads_from_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "google_client_secret.txt"
    secret_file.write_text("google-client-secret-from-file\n", encoding="utf-8")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET_FILE", str(secret_file))

    load_secret_env()

    settings = Settings(_env_file=None)

    assert settings.GOOGLE_CLIENT_SECRET == "google-client-secret-from-file"


def test_tavily_api_key_loads_from_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "tavily_api_key.txt"
    secret_file.write_text("tvly-secret-from-file\n", encoding="utf-8")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY_FILE", str(secret_file))

    load_secret_env()

    settings = Settings(_env_file=None)

    assert settings.TAVILY_API_KEY == "tvly-secret-from-file"


def test_non_local_web_config_rejects_default_secret_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("SECRET_KEY", DEFAULT_SECRET_KEY)
    monkeypatch.setenv("GOOGLE_ALLOWED_REDIRECT_URIS", "https://example.com/callback")
    get_web_settings.cache_clear()

    exit_code = run_checks("web")

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "SECRET_KEY must not use the local default outside local" in captured.out


def test_production_settings_reject_default_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRET_KEY", DEFAULT_SECRET_KEY)

    with pytest.raises(
        ValueError,
        match="SECRET_KEY must not use the local default outside local",
    ):
        Settings(_env_file=None)


def test_non_local_settings_reject_short_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "short-secret")

    with pytest.raises(ValueError, match="SECRET_KEY is short"):
        Settings(_env_file=None)


def test_production_settings_reject_sms_mock_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRET_KEY", PROD_SECRET_KEY)
    monkeypatch.setenv("SMS_MOCK_MODE", "true")

    with pytest.raises(ValueError, match="SMS_MOCK_MODE must be False in production"):
        Settings(_env_file=None)


def test_cors_defaults_are_wildcard_for_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("BACKEND_CORS_METHODS", raising=False)
    monkeypatch.delenv("BACKEND_CORS_HEADERS", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.BACKEND_CORS_METHODS == ["*"]
    assert settings.BACKEND_CORS_HEADERS == ["*"]


def test_cors_defaults_are_restricted_for_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("BACKEND_CORS_METHODS", raising=False)
    monkeypatch.delenv("BACKEND_CORS_HEADERS", raising=False)
    monkeypatch.setenv("SECRET_KEY", PROD_SECRET_KEY)
    monkeypatch.setenv("GOOGLE_ALLOWED_REDIRECT_URIS", "https://example.com/callback")

    settings = Settings(_env_file=None)

    assert settings.BACKEND_CORS_METHODS == [
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ]
    assert settings.BACKEND_CORS_HEADERS == [
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "X-Idempotency-Key",
    ]


def test_production_cors_defaults_allow_frontend_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("BACKEND_CORS_METHODS", raising=False)
    monkeypatch.delenv("BACKEND_CORS_HEADERS", raising=False)
    monkeypatch.setenv("SECRET_KEY", PROD_SECRET_KEY)
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("GOOGLE_ALLOWED_REDIRECT_URIS", "https://example.com/callback")

    settings = Settings(_env_file=None)
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=settings.BACKEND_CORS_METHODS,
        allow_headers=settings.BACKEND_CORS_HEADERS,
    )
    client = TestClient(app)

    patch_response = client.options(
        "/",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": (
                "authorization,content-type,x-request-id"
            ),
        },
    )
    idempotent_post_response = client.options(
        "/",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "authorization,content-type,x-request-id,x-idempotency-key"
            ),
        },
    )

    assert patch_response.status_code == 200
    assert idempotent_post_response.status_code == 200


def test_google_oauth_can_be_disabled_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRET_KEY", PROD_SECRET_KEY)
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "false")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_ALLOWED_REDIRECT_URIS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.GOOGLE_OAUTH_ENABLED is False
    assert settings.GOOGLE_ALLOWED_REDIRECT_URIS == []


def test_google_oauth_enabled_requires_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRET_KEY", PROD_SECRET_KEY)
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_ALLOWED_REDIRECT_URIS", raising=False)

    with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
        Settings(_env_file=None)


def test_cors_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("BACKEND_CORS_METHODS", "GET,POST")
    monkeypatch.setenv("BACKEND_CORS_HEADERS", "Authorization,Content-Type")
    monkeypatch.setenv("SECRET_KEY", PROD_SECRET_KEY)
    monkeypatch.setenv("GOOGLE_ALLOWED_REDIRECT_URIS", "https://example.com/callback")

    settings = Settings(_env_file=None)

    assert settings.BACKEND_CORS_METHODS == ["GET", "POST"]
    assert settings.BACKEND_CORS_HEADERS == ["Authorization", "Content-Type"]


def test_cors_defaults_follow_yaml_app_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    app_dir = config_dir / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "base.yaml").write_text("APP_ENV: production\n", encoding="utf-8")

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("SECRET_KEY", PROD_SECRET_KEY)
    monkeypatch.setenv("GOOGLE_ALLOWED_REDIRECT_URIS", "https://example.com/callback")

    settings = Settings()

    assert settings.APP_ENV == "production"
    assert settings.BACKEND_CORS_METHODS == [
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ]
    assert settings.BACKEND_CORS_HEADERS == [
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "X-Idempotency-Key",
    ]


def test_app_env_loads_layered_yaml_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    app_dir = config_dir / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "base.yaml").write_text(
        "STORAGE_BACKEND: local\nLOCAL_STORAGE_ROOT: base-files\n",
        encoding="utf-8",
    )
    (app_dir / "test.yaml").write_text(
        "APP_ENV: test\nLOCAL_STORAGE_ROOT: test-files\nLLM_PROVIDER: mock\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)

    settings = Settings()

    assert settings.APP_ENV == "test"
    assert settings.STORAGE_BACKEND == "local"
    assert settings.local_storage_root == Path("test-files")
    assert settings.LLM_PROVIDER == "mock"


def test_environment_overrides_app_yaml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    app_dir = config_dir / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "base.yaml").write_text("STORAGE_BACKEND: local\n", encoding="utf-8")
    (app_dir / "test.yaml").write_text(
        "LOCAL_STORAGE_ROOT: yaml-files\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", "env-files")
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)

    settings = Settings()

    assert settings.local_storage_root == Path("env-files")


def test_database_url_overrides_postgres_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)

    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://db-user:db-pass@rdc.example.com:5432/prod",
        POSTGRES_SERVER="localhost",
    )

    assert "rdc.example.com" in settings.database_url
    assert "localhost" not in settings.database_url
    assert "db-pass" not in settings.database_url_safe


def test_cors_empty_string_parses_to_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("BACKEND_CORS_METHODS", "")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.BACKEND_CORS_METHODS == []


def test_cors_whitespace_comma_parses_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("BACKEND_CORS_HEADERS", " Authorization , Content-Type , ")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.BACKEND_CORS_HEADERS == ["Authorization", "Content-Type"]


def test_rate_limit_settings_load_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)
    monkeypatch.setenv("AUTH_REGISTER_RATE_LIMIT_TIMES", "101")
    monkeypatch.setenv("AUTH_REGISTER_RATE_LIMIT_SECONDS", "61")
    monkeypatch.setenv("AUTH_LOGIN_RATE_LIMIT_TIMES", "102")
    monkeypatch.setenv("AUTH_LOGIN_RATE_LIMIT_SECONDS", "62")
    monkeypatch.setenv("AUTH_SMS_LOGIN_RATE_LIMIT_TIMES", "103")
    monkeypatch.setenv("AUTH_SMS_LOGIN_RATE_LIMIT_SECONDS", "63")
    monkeypatch.setenv("AUTH_GOOGLE_CALLBACK_RATE_LIMIT_TIMES", "104")
    monkeypatch.setenv("AUTH_GOOGLE_CALLBACK_RATE_LIMIT_SECONDS", "64")
    monkeypatch.setenv("SMS_VERIFY_FAILURE_LIMIT", "6")
    monkeypatch.setenv("SMS_VERIFY_FAILURE_WINDOW_SECONDS", "301")
    monkeypatch.setenv("SMS_VERIFY_LOCKOUT_SECONDS", "601")
    monkeypatch.setenv("BUSINESS_RATE_LIMIT_TIMES", "103")
    monkeypatch.setenv("BUSINESS_RATE_LIMIT_SECONDS", "63")
    monkeypatch.setenv("CHAT_RATE_LIMIT_TIMES", "104")
    monkeypatch.setenv("CHAT_RATE_LIMIT_SECONDS", "64")
    monkeypatch.setenv("FRONTEND_TELEMETRY_RATE_LIMIT_TIMES", "105")
    monkeypatch.setenv("FRONTEND_TELEMETRY_RATE_LIMIT_SECONDS", "65")
    monkeypatch.setenv("CSP_REPORT_RATE_LIMIT_TIMES", "106")
    monkeypatch.setenv("CSP_REPORT_RATE_LIMIT_SECONDS", "66")

    settings = Settings(_env_file=None)

    assert settings.AUTH_REGISTER_RATE_LIMIT_TIMES == 101
    assert settings.AUTH_REGISTER_RATE_LIMIT_SECONDS == 61
    assert settings.AUTH_LOGIN_RATE_LIMIT_TIMES == 102
    assert settings.AUTH_LOGIN_RATE_LIMIT_SECONDS == 62
    assert settings.AUTH_SMS_LOGIN_RATE_LIMIT_TIMES == 103
    assert settings.AUTH_SMS_LOGIN_RATE_LIMIT_SECONDS == 63
    assert settings.AUTH_GOOGLE_CALLBACK_RATE_LIMIT_TIMES == 104
    assert settings.AUTH_GOOGLE_CALLBACK_RATE_LIMIT_SECONDS == 64
    assert settings.SMS_VERIFY_FAILURE_LIMIT == 6
    assert settings.SMS_VERIFY_FAILURE_WINDOW_SECONDS == 301
    assert settings.SMS_VERIFY_LOCKOUT_SECONDS == 601
    assert settings.BUSINESS_RATE_LIMIT_TIMES == 103
    assert settings.BUSINESS_RATE_LIMIT_SECONDS == 63
    assert settings.CHAT_RATE_LIMIT_TIMES == 104
    assert settings.CHAT_RATE_LIMIT_SECONDS == 64
    assert settings.FRONTEND_TELEMETRY_RATE_LIMIT_TIMES == 105
    assert settings.FRONTEND_TELEMETRY_RATE_LIMIT_SECONDS == 65
    assert settings.CSP_REPORT_RATE_LIMIT_TIMES == 106
    assert settings.CSP_REPORT_RATE_LIMIT_SECONDS == 66


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("SMS_VERIFY_FAILURE_LIMIT", "-1"),
        ("SMS_VERIFY_FAILURE_WINDOW_SECONDS", "0"),
        ("SMS_VERIFY_LOCKOUT_SECONDS", "0"),
    ],
)
def test_sms_verify_settings_reject_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
) -> None:
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)
    monkeypatch.setenv(env_name, env_value)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_web_settings_load_sms_verify_values_from_yaml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    app_dir = config_dir / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "base.yaml").write_text(
        "SMS_VERIFY_FAILURE_LIMIT: 3\n"
        "SMS_VERIFY_FAILURE_WINDOW_SECONDS: 45\n"
        "SMS_VERIFY_LOCKOUT_SECONDS: 90\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)
    get_web_settings.cache_clear()

    settings = get_web_settings()

    assert settings.SMS_VERIFY_FAILURE_LIMIT == 3
    assert settings.SMS_VERIFY_FAILURE_WINDOW_SECONDS == 45
    assert settings.SMS_VERIFY_LOCKOUT_SECONDS == 90
    get_web_settings.cache_clear()


def test_rag_refusal_settings_can_load_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)
    monkeypatch.setenv("RAG_MIN_HIT_COUNT", "2")
    monkeypatch.setenv("RAG_MIN_RELEVANCE_SCORE", "0.35")
    monkeypatch.setenv("RAG_MIN_RERANK_SCORE", "6.5")
    monkeypatch.setenv("RAG_REFUSAL_MESSAGE", "资料不足，无法回答。")
    monkeypatch.setenv("RAG_PLANNER_REFUSAL_CONFIDENCE_THRESHOLD", "0.75")
    monkeypatch.setenv("RAG_PLANNER_REFUSAL_MESSAGE", "planner 拒答。")

    settings = Settings()

    assert settings.RAG_MIN_HIT_COUNT == 2
    assert settings.RAG_MIN_RELEVANCE_SCORE == 0.35
    assert settings.RAG_MIN_RERANK_SCORE == 6.5
    assert settings.RAG_REFUSAL_MESSAGE == "资料不足，无法回答。"
    assert settings.RAG_PLANNER_REFUSAL_CONFIDENCE_THRESHOLD == 0.75
    assert settings.RAG_PLANNER_REFUSAL_MESSAGE == "planner 拒答。"


def test_rag_planner_enabled_default_from_yaml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    app_dir = config_dir / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "base.yaml").write_text(
        "LLM_PROVIDER: bifrost_pro\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)

    settings = Settings()

    assert settings.LLM_PROVIDER == "bifrost_pro"


def test_bifrost_pro_alias_resolves_to_v4_pro_profile() -> None:
    from backend.config.llm import get_llm_model_config

    config = get_llm_model_config()
    profile = config.resolve_profile("bifrost_pro")

    assert profile.name == "bifrost_v4_pro"
    assert profile.model == "deepseek/deepseek-v4-pro"
    assert profile.provider == "openai-compatible"


def test_bifrost_flash_alias_resolves_to_v4_flash_profile() -> None:
    from backend.config.llm import get_llm_model_config

    config = get_llm_model_config()
    profile = config.resolve_profile("bifrost_flash")

    assert profile.name == "bifrost_v4_flash"
    assert profile.model == "deepseek/deepseek-v4-flash"
    assert profile.provider == "openai-compatible"


def test_deepseek_pro_alias_resolves_to_v4_pro_profile() -> None:
    from backend.config.llm import get_llm_model_config

    config = get_llm_model_config()
    profile = config.resolve_profile("deepseek_pro")

    assert profile.name == "deepseek_v4_pro"
    assert profile.model == "deepseek-v4-pro"
    assert profile.provider == "deepseek"


def test_rag_planner_provider_deepseek_resolves_to_flash_profile() -> None:
    from backend.config.llm import get_llm_model_config

    config = get_llm_model_config()
    profile = config.resolve_profile("deepseek")

    assert profile.name == "deepseek_v4_flash"
    assert profile.model == "deepseek-v4-flash"
