"""Application settings.

职责：合并环境变量、dotenv、Docker secrets 和 YAML 配置，生成应用运行设置。
边界：本模块不创建数据库、Redis 或 LLM 客户端；只提供配置值和派生 URL。
副作用：导入时会加载受支持的 *_FILE secret 到环境变量。
"""

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import yaml
from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from sqlalchemy.engine import URL, make_url

import backend.core.secret_env  # noqa: F401

_logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _current_app_env() -> str:
    return os.getenv("APP_ENV", "local").strip().lower() or "local"


def _config_dir() -> Path:
    raw_config_dir = os.getenv("CONFIG_DIR")
    if raw_config_dir:
        path = Path(raw_config_dir)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path
    return BASE_DIR / "configs"


def _env_files() -> tuple[str, ...] | None:
    files = []
    base_env = BASE_DIR / ".env"
    if base_env.exists():
        files.append(str(base_env))
    app_env_file = BASE_DIR / f".env.{_current_app_env()}"
    if app_env_file.exists():
        files.append(str(app_env_file))
    return tuple(files) or None


class AppYamlSettingsSource(PydanticBaseSettingsSource):
    """把 app/base.yaml 和 app/{APP_ENV}.yaml 接入 Pydantic Settings。"""

    def get_field_value(self, field, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        config: dict[str, Any] = {}
        app_env = str(self.current_state.get("APP_ENV") or _current_app_env())
        config_dir = self.current_state.get("CONFIG_DIR") or _config_dir()
        config_dir = Path(config_dir)
        if not config_dir.is_absolute():
            config_dir = BASE_DIR / config_dir
        for filename in ("base.yaml", f"{app_env}.yaml"):
            path = config_dir / "app" / filename
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ValueError(f"App config file must contain a mapping: {path}")
            config.update(data)
        known_fields = self.settings_cls.model_fields
        unknown_keys = [k for k in config if k not in known_fields]
        if unknown_keys:
            _logger.warning(
                "AppYamlSettings: 以下配置键未被识别，已忽略（请检查拼写）: %s",
                unknown_keys,
            )
        return {
            key: value
            for key, value in config.items()
            if key in known_fields
        }


class Settings(BaseSettings):
    """应用配置值和少量派生属性。"""

    # 路径类配置保持为 Path，避免调用方重复做字符串转换。
    APP_ENV: str = Field(default_factory=_current_app_env)
    CONFIG_DIR: Path = Field(default_factory=_config_dir)
    BASE_DIR: Path = BASE_DIR
    LOG_DIR: Path = BASE_DIR / "logs/backend"

    PROJECT_NAME: str = "Obsidian Mentor AI"
    VERSION: str = "0.1.0"
    API_ROOT_PATH: str = "/api"
    API_V1_STR: str = "/v1"

    DATABASE_URL: str | None = None
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "mentor_ai"
    POSTGRES_DB_ECHO: bool = False  # 生产环境建议关闭，开发环境可开启
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20
    POSTGRES_SSL_MODE: str | None = None
    POSTGRES_CONNECT_TIMEOUT_SECONDS: int = Field(default=10, ge=1)

    BATCH_SIZE: int = 500

    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    DEEPSEEK_API_KEY: str | None = None

    OBSIDIAN_VAULT_PATH: str = "/data/obsidian"
    # 兼容旧配置名；实际读取优先级在 local_storage_root property 中统一处理。
    KNOWLEDGE_STORAGE_ROOT: Path = Path(".files/knowledge_files")
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_ROOT: Path | None = None  # 替代 KNOWLEDGE_STORAGE_ROOT，优先级更高
    KNOWLEDGE_MAX_UPLOAD_SIZE_MB: int = 20
    KNOWLEDGE_CHUNK_SIZE: int = 800
    KNOWLEDGE_CHUNK_OVERLAP: int = 120
    S3_BUCKET: str | None = None
    S3_PREFIX: str = "knowledge_files"
    S3_REGION: str | None = None
    S3_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None

    REDIS_URL: str | None = None
    TASKIQ_REDIS_URL: str | None = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None

    LLM_MAX_CONCURRENCY: int = 5
    DB_MAX_CONCURRENCY: int = 10
    RATE_LIMIT_TRUSTED_PROXY_CIDRS: str = ""
    # 限流参数必须可通过环境覆盖，压测和生产会使用不同阈值。
    CHAT_RATE_LIMIT_TIMES: int = 10
    CHAT_RATE_LIMIT_SECONDS: int = 60

    LLM_PROVIDER: str = "mock"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    LLM_MAX_CONTEXT_TOKENS: int = 4096
    LLM_MAX_HISTORY_ROUNDS: int = 10
    LLM_RESERVED_RESPONSE_TOKENS: int = 1024
    CHAT_STREAM_FIRST_MESSAGE_TIMEOUT_SECONDS: int = 30
    CHAT_MEMORY_RECENT_ROUNDS: int = 6
    CHAT_MEMORY_SUMMARY_MAX_CHARS: int = 1500
    CHAT_MEMORY_SNIPPET_CHARS: int = 120
    CHAT_MEMORY_FETCH_LIMIT: int = 2000
    RAG_TOP_K: int = 4
    RAG_EMBED_PROVIDER: str = "google"
    RAG_EMBED_BASE_URL: str | None = None
    RAG_EMBED_API_KEY: str | None = None
    RAG_EMBED_DIM: int = Field(default=768, ge=1)
    RAG_EMBED_BATCH_SIZE: int = Field(default=32, ge=1, le=256)

    # SECRET_KEY 不提供默认值，避免本地默认密钥进入生产。
    SECRET_KEY: str = Field(..., min_length=1)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

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
        return connect_args

    @property
    def local_storage_root(self) -> Path:
        return self.LOCAL_STORAGE_ROOT or self.KNOWLEDGE_STORAGE_ROOT

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
        """应用主 Redis 连接地址（优先使用 REDIS_URL）。"""
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
        """TaskIQ Redis 连接地址（可单独覆盖，默认使用 DB1）。"""
        if self.TASKIQ_REDIS_URL:
            return self.TASKIQ_REDIS_URL
        if self.REDIS_URL:
            return self._replace_redis_db(self.REDIS_URL, db=1)
        return self._build_redis_url(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            password=self.REDIS_PASSWORD,
            db=1,
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

    @staticmethod
    def _replace_redis_db(url: str, db: int) -> str:
        parsed = urlsplit(url)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, f"/{db}", parsed.query, parsed.fragment)
        )

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
        if normalized not in {"disable", "require"}:
            raise ValueError("POSTGRES_SSL_MODE must be one of: disable, require")
        return normalized

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SECRET_KEY must not be empty")
        return value


@lru_cache
def get_settings() -> Settings:
    """返回进程级缓存的 Settings。"""
    return Settings()


settings = get_settings()
