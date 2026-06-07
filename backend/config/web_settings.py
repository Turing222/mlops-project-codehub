"""Web / HTTP API settings.

职责：管理 FastAPI 应用的路由、鉴权、限流等 Web-only 配置。
边界：不包含 DB/Redis/Storage 等基础设施配置，不包含 AI/LLM 模型配置。
副作用：导入时加载 *_FILE secret 到环境变量。
"""

import os
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from backend.config.ai_settings import AppYamlSettingsSource, _env_files

DEFAULT_SECRET_KEY = "local-dev-secret"  # noqa: S105
PRODUCTION_APP_ENVS = {"prod", "production"}
PRODUCTION_CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
PRODUCTION_CORS_HEADERS = [
    "Authorization",
    "Content-Type",
    "X-Request-ID",
    "X-Idempotency-Key",
]
PRODUCTION_CORS_EXPOSE_HEADERS = ["X-Request-ID", "X-Trace-ID", "X-Process-Time"]
MIN_NON_LOCAL_SECRET_KEY_LENGTH = 32


def normalize_app_env(app_env: str | None) -> str:
    return (app_env or "local").strip().lower() or "local"


def is_local_app_env(app_env: str | None) -> bool:
    return normalize_app_env(app_env) == "local"


def is_production_app_env(app_env: str | None) -> bool:
    return normalize_app_env(app_env) in PRODUCTION_APP_ENVS


def _current_app_env() -> str:
    return normalize_app_env(os.getenv("APP_ENV"))


def _default_cors_methods() -> list[str]:
    if is_production_app_env(_current_app_env()):
        return PRODUCTION_CORS_METHODS.copy()
    return ["*"]


def _default_cors_headers() -> list[str]:
    if is_production_app_env(_current_app_env()):
        return PRODUCTION_CORS_HEADERS.copy()
    return ["*"]


def _cors_defaults_for_env(app_env: str) -> tuple[list[str], list[str], list[str]]:
    if is_production_app_env(app_env):
        return (
            PRODUCTION_CORS_METHODS.copy(),
            PRODUCTION_CORS_HEADERS.copy(),
            PRODUCTION_CORS_EXPOSE_HEADERS.copy(),
        )
    return ["*"], ["*"], PRODUCTION_CORS_EXPOSE_HEADERS.copy()


class WebSettings(BaseSettings):
    """Web API 配置 —— 路由、鉴权、限流。"""

    # ── App Metadata ──────────────────────────────────────────────
    APP_ENV: str = Field(default_factory=_current_app_env)
    PROJECT_NAME: str = "Dewflow AI"
    VERSION: str = "2.0.0"
    DEBUG: bool = False
    API_ROOT_PATH: str = "/api"
    API_V1_STR: str = "/v1"

    # ── Auth ──────────────────────────────────────────────────────
    SECRET_KEY: str = Field(DEFAULT_SECRET_KEY, min_length=1)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── Google OAuth ──────────────────────────────────────────────
    GOOGLE_OAUTH_ENABLED: bool = Field(False, description="Enable Google OAuth2 login")
    GOOGLE_CLIENT_ID: str = Field("", description="Google OAuth2 Client ID")
    GOOGLE_CLIENT_SECRET: str = Field("", description="Google OAuth2 Client Secret")
    GOOGLE_ALLOWED_REDIRECT_URIS: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Google OAuth2 允许的 redirect_uri 白名单（逗号分隔）",
    )

    # ── SMS Verification ──────────────────────────────────────────
    SMS_CODE_EXPIRE_SECONDS: int = Field(300, description="短信验证码有效期（秒）")
    SMS_CODE_RATE_LIMIT_SECONDS: int = Field(60, description="同一手机号发送间隔（秒）")
    SMS_SEND_RATE_LIMIT_TIMES: int = Field(5, description="短信发送接口限流次数")
    SMS_SEND_RATE_LIMIT_SECONDS: int = Field(
        60, description="短信发送接口限流窗口（秒）"
    )
    SMS_VERIFY_FAILURE_LIMIT: int = Field(
        5,
        ge=0,
        description="短信验证码校验失败锁定阈值；0 表示禁用手机号锁定",
    )
    SMS_VERIFY_FAILURE_WINDOW_SECONDS: int = Field(
        300, gt=0, description="短信验证码校验失败统计窗口（秒）"
    )
    SMS_VERIFY_LOCKOUT_SECONDS: int = Field(
        600, gt=0, description="短信验证码校验失败后的临时锁定时间（秒）"
    )
    SMS_MOCK_MODE: bool = Field(False, description="Mock 模式下验证码仅写入日志")

    # ── Rate Limiting ─────────────────────────────────────────────
    RATE_LIMIT_TRUSTED_PROXY_CIDRS: str = ""
    AUTH_REGISTER_RATE_LIMIT_TIMES: int = 10
    AUTH_REGISTER_RATE_LIMIT_SECONDS: int = 60
    AUTH_LOGIN_RATE_LIMIT_TIMES: int = 20
    AUTH_LOGIN_RATE_LIMIT_SECONDS: int = 60
    AUTH_SMS_LOGIN_RATE_LIMIT_TIMES: int = 10
    AUTH_SMS_LOGIN_RATE_LIMIT_SECONDS: int = 60
    AUTH_GOOGLE_CALLBACK_RATE_LIMIT_TIMES: int = 10
    AUTH_GOOGLE_CALLBACK_RATE_LIMIT_SECONDS: int = 60
    BUSINESS_RATE_LIMIT_TIMES: int = 100
    BUSINESS_RATE_LIMIT_SECONDS: int = 60
    CHAT_RATE_LIMIT_TIMES: int = 10
    CHAT_RATE_LIMIT_SECONDS: int = 60
    FRONTEND_TELEMETRY_RATE_LIMIT_TIMES: int = 300
    FRONTEND_TELEMETRY_RATE_LIMIT_SECONDS: int = 60
    CSP_REPORT_RATE_LIMIT_TIMES: int = 300
    CSP_REPORT_RATE_LIMIT_SECONDS: int = 60

    # ── CORS ──────────────────────────────────────────────────────
    BACKEND_CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=list)
    BACKEND_CORS_METHODS: Annotated[list[str], NoDecode] = Field(
        default_factory=_default_cors_methods
    )
    BACKEND_CORS_HEADERS: Annotated[list[str], NoDecode] = Field(
        default_factory=_default_cors_headers
    )
    BACKEND_CORS_EXPOSE_HEADERS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: PRODUCTION_CORS_EXPOSE_HEADERS.copy()
    )

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            AppYamlSettingsSource(settings_cls),
        )

    @model_validator(mode="before")
    @classmethod
    def apply_environment_cors_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        app_env = str(values.get("APP_ENV") or _current_app_env())
        default_methods, default_headers, default_expose_headers = (
            _cors_defaults_for_env(app_env)
        )
        values.setdefault("BACKEND_CORS_METHODS", default_methods)
        values.setdefault("BACKEND_CORS_HEADERS", default_headers)
        values.setdefault("BACKEND_CORS_EXPOSE_HEADERS", default_expose_headers)
        return values

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SECRET_KEY must not be empty")
        return value

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_flag(cls, value: Any) -> Any:
        if isinstance(value, str):
            val = value.strip().lower()
            if val == "release":
                return False
            if val == "debug":
                return True
        return value

    @field_validator(
        "BACKEND_CORS_ORIGINS",
        "BACKEND_CORS_METHODS",
        "BACKEND_CORS_HEADERS",
        "BACKEND_CORS_EXPOSE_HEADERS",
        "GOOGLE_ALLOWED_REDIRECT_URIS",
        mode="before",
    )
    @classmethod
    def parse_cors_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                # 空字符串 → []，语义上是禁用所有方法/头/源。
                # 如果你想用默认值而不是禁用到所有，请直接不设这个 env var。
                return []
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_production_security(self) -> "WebSettings":
        if not is_local_app_env(self.APP_ENV):
            secret_key = self.SECRET_KEY.strip()
            if secret_key == DEFAULT_SECRET_KEY:
                raise ValueError(
                    "SECRET_KEY must not use the local default outside local"
                )
            if len(secret_key) < MIN_NON_LOCAL_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"SECRET_KEY is short ({len(secret_key)} chars); "
                    "use >=32 chars for non-local environments"
                )
        if is_production_app_env(self.APP_ENV) and self.SMS_MOCK_MODE:
            raise ValueError("SMS_MOCK_MODE must be False in production")
        if self.GOOGLE_OAUTH_ENABLED:
            if not self.GOOGLE_CLIENT_ID.strip():
                raise ValueError(
                    "GOOGLE_CLIENT_ID must be set when Google OAuth is enabled"
                )
            if not self.GOOGLE_CLIENT_SECRET.strip():
                raise ValueError(
                    "GOOGLE_CLIENT_SECRET must be set when Google OAuth is enabled"
                )
            if not self.GOOGLE_ALLOWED_REDIRECT_URIS:
                raise ValueError(
                    "GOOGLE_ALLOWED_REDIRECT_URIS must be set when Google OAuth is enabled"
                )
        return self


@lru_cache
def get_web_settings() -> WebSettings:
    return WebSettings()
