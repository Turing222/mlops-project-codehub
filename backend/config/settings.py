"""Application settings.

职责：合并环境变量、dotenv、Docker secrets 和 YAML 配置，生成应用运行设置。
边界：本模块不创建数据库、Redis 或 LLM 客户端；只提供配置值和派生 URL。
副作用：导入时会加载受支持的 *_FILE secret 到环境变量。
"""

import logging
import ssl
from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import quote

from pydantic import Field, field_validator, model_validator
from sqlalchemy.engine import URL, make_url

from backend.config.ai_settings import BASE_DIR, AISettings, _config_dir
from backend.config.web_settings import WebSettings, is_production_app_env
from backend.config.worker_settings import WorkerSettings

_logger = logging.getLogger(__name__)


class Settings(WebSettings, AISettings, WorkerSettings):
    """Application settings — aggregates Web, AI, and Worker configs.

    应用配置 —— 继承 Web/AI/Worker 配置，追加共享 DB/Redis/Storage 基础设施字段。

    旧代码可继续通过 backend.config.settings 聚合导入所有配置。
    新代码优先导入更具体的 settings：
      - Web:  backend.config.web_settings
      - Worker: backend.config.worker_settings + backend.config.ai_settings
    """

    # ── App Metadata ──────────────────────────────────────────────
    CONFIG_DIR: Path = Field(default_factory=_config_dir)
    BASE_DIR: Path = BASE_DIR
    LOG_DIR: Path = BASE_DIR / "logs/backend"
    BACKEND_LOG_LEVEL: str = "info"

    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str | None = None
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "dewflow"
    POSTGRES_DB_ECHO: bool = False
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20
    POSTGRES_SSL_MODE: str | None = None
    POSTGRES_SSL_ROOT_CERT_FILE: Path | None = None
    POSTGRES_CONNECT_TIMEOUT_SECONDS: int = Field(default=10, ge=1)

    BATCH_SIZE: int = 500

    # ── Redis ─────────────────────────────────────────────────────
    REDIS_URL: str | None = None
    TASKIQ_REDIS_URL: str | None = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    TASKIQ_REDIS_HOST: str = "localhost"
    TASKIQ_REDIS_PORT: int = Field(default=6380, ge=1, le=65535)
    TASKIQ_RESULT_TTL_SECONDS: int = Field(default=3600, ge=60, le=604800)

    # ── Storage ───────────────────────────────────────────────────
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_ROOT: Path = Path(".files/knowledge_files")
    S3_BUCKET: str | None = None
    S3_PREFIX: str = "knowledge_files"
    S3_REGION: str | None = None
    S3_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None

    # ── Observability ───────────────────────────────────────────────
    ENABLE_OTEL_METRICS: bool = True
    ENABLE_OTEL_TRACES: bool = False
    OTEL_METRICS_ENDPOINT: str = "http://prometheus:9090/api/v1/otlp/v1/metrics"
    OTEL_TRACES_ENDPOINT: str = "http://jaeger:4318/v1/traces"
    TELEMETRY_CAPTURE_CONTENT: bool = False

    # ── GrowthBook ──────────────────────────────────────────────────
    GROWTHBOOK_API_HOST: str = "https://cdn.growthbook.io"
    GROWTHBOOK_SDK_KEY: str = "sdk-dummy-key-for-development"
    GROWTHBOOK_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    GROWTHBOOK_CIRCUIT_BREAKER_COOLDOWN_SECONDS: int = 30
    BETA_USER_EMAIL_WHITELIST: str = "tony@company.com,tester@dewflow.com"
    BETA_USER_PHONE_WHITELIST: str = ""

    # ── GitHub ─────────────────────────────────────────────────────
    GITHUB_TOKEN: str | None = None

    # ── Properties ────────────────────────────────────────────────

    @property
    def database_url(self) -> str:
        return self._database_url_obj().render_as_string(hide_password=False)

    @property
    def database_url_safe(self) -> str:
        return self._database_url_obj().render_as_string(hide_password=True)

    @property
    def database_connect_args(self) -> dict[str, object]:
        connect_args: dict[str, object] = {
            "timeout": self.POSTGRES_CONNECT_TIMEOUT_SECONDS
        }
        ssl_mode = (self.POSTGRES_SSL_MODE or "").strip().lower()
        if ssl_mode == "disable":
            connect_args["ssl"] = False
        elif ssl_mode == "require":
            connect_args["ssl"] = True
        elif ssl_mode in {"verify-ca", "verify-full"}:
            connect_args["ssl"] = self._postgres_ssl_context(
                check_hostname=ssl_mode == "verify-full",
            )
        return connect_args

    def _postgres_ssl_context(self, *, check_hostname: bool) -> ssl.SSLContext:
        cafile = (
            str(self.POSTGRES_SSL_ROOT_CERT_FILE)
            if self.POSTGRES_SSL_ROOT_CERT_FILE
            else None
        )
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=cafile)
        context.check_hostname = check_hostname
        return context

    @property
    def local_storage_root(self) -> Path:
        return self.LOCAL_STORAGE_ROOT

    def _database_url_obj(self) -> URL:
        if self.DATABASE_URL:
            return make_url(self.DATABASE_URL)
        return self._build_database_url()

    def _build_database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )

    @property
    def redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        return self._build_redis_url(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            password=self.REDIS_PASSWORD,
            db=0,
        )

    @property
    def taskiq_redis_url(self) -> str:
        if self.TASKIQ_REDIS_URL:
            return self.TASKIQ_REDIS_URL
        return self._build_redis_url(
            host=self.TASKIQ_REDIS_HOST,
            port=self.TASKIQ_REDIS_PORT,
            password=self.REDIS_PASSWORD,
            db=0,
        )

    @staticmethod
    def _build_redis_url(
        *,
        host: str,
        port: int,
        password: str | None,
        db: int,
    ) -> str:
        auth = f":{quote(password, safe='')}@" if password else ""
        return f"redis://{auth}{host}:{port}/{db}"

    # ── Validators ────────────────────────────────────────────────

    @field_validator("STORAGE_BACKEND")
    @classmethod
    def validate_storage_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "s3"}:
            raise ValueError("STORAGE_BACKEND must be one of: local, s3")
        return normalized

    @field_validator("POSTGRES_SSL_MODE")
    @classmethod
    def validate_postgres_ssl_mode(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if normalized not in {"disable", "require", "verify-ca", "verify-full"}:
            raise ValueError(
                "POSTGRES_SSL_MODE must be one of: disable, require, verify-ca, verify-full"
            )
        return normalized

    @field_validator("POSTGRES_SSL_ROOT_CERT_FILE", mode="before")
    @classmethod
    def normalize_postgres_ssl_root_cert_file(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_postgres_ssl_root_cert_file(self) -> Self:
        ssl_mode = (self.POSTGRES_SSL_MODE or "").strip().lower()
        if ssl_mode not in {"verify-ca", "verify-full"}:
            return self
        if self.POSTGRES_SSL_ROOT_CERT_FILE is None:
            return self
        cert_path = self.POSTGRES_SSL_ROOT_CERT_FILE
        if not cert_path.is_file():
            raise ValueError(
                f"POSTGRES_SSL_ROOT_CERT_FILE 不存在或不是文件: {cert_path}"
            )
        return self

    @model_validator(mode="after")
    def validate_telemetry_content_capture(self) -> Self:
        if is_production_app_env(self.APP_ENV) and self.TELEMETRY_CAPTURE_CONTENT:
            raise ValueError("TELEMETRY_CAPTURE_CONTENT must be False in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
