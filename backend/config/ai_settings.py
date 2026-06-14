"""AI-specific application settings.

职责：管理 LLM、RAG、Embedding、Chat Memory 等 AI 相关配置。
边界：不包含 Web/DB/Redis/Auth 等基础设施配置。
副作用：导入时加载 *_FILE secret 到环境变量。
"""

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

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
        # YAML 中的部分字段可能属于其他 Settings 子类（如 AISettings vs Settings），
        # 仅当字段不属于任何已知配置类时才发出提示。
        return {key: value for key, value in config.items() if key in known_fields}


class AISettings(BaseSettings):
    """AI 相关配置 —— LLM provider、RAG、Embedding、Chat Memory。"""

    # ── LLM Provider Keys ──────────────────────────────────────────
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    DEEPSEEK_API_KEY: str | None = None
    DASHSCOPE_API_KEY: str | None = None
    BIFROST_API_KEY: str | None = None
    # ── LLM Provider Config ───────────────────────────────────────
    LLM_PROVIDER: str = "mock"
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # ── LLM Behavior ──────────────────────────────────────────────
    LLM_MAX_CONTEXT_TOKENS: int = 8192
    LLM_MAX_HISTORY_ROUNDS: int = 10
    LLM_RESERVED_RESPONSE_TOKENS: int = 1024
    LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS: int = 30
    LLM_MODEL_ROUTE_FAST_PROVIDER: str = "bifrost_flash"
    LLM_MODEL_ROUTE_BALANCED_PROVIDER: str = "bifrost_pro"
    LLM_MODEL_ROUTE_REASONING_PROVIDER: str = "bifrost_reasoner"
    LLM_MODEL_ROUTE_MIN_CONFIDENCE: float = Field(default=0.65, ge=0.0, le=1.0)

    # ── Chat Stream Timeouts ──────────────────────────────────────
    CHAT_STREAM_FIRST_MESSAGE_TIMEOUT_SECONDS: int = 30
    CHAT_STREAM_MESSAGE_TIMEOUT_SECONDS: int = 10

    # ── Chat Memory ───────────────────────────────────────────────
    CHAT_MEMORY_RECENT_ROUNDS: int = 6
    CHAT_MEMORY_SUMMARY_MAX_CHARS: int = 1500
    CHAT_MEMORY_SNIPPET_CHARS: int = 120
    CHAT_MEMORY_FETCH_LIMIT: int = 2000

    # ── RAG Retrieval ─────────────────────────────────────────────
    RAG_TOP_K: int = 4
    RAG_RERANK_PROVIDER: str | None = None
    RAG_RERANK_BASE_URL: str | None = None
    RAG_RERANK_MODEL: str = "qwen3-rerank"
    RAG_RERANK_TIMEOUT_SECONDS: int = Field(default=15, ge=1, le=60)
    RAG_RERANK_CANDIDATE_COUNT: int = Field(default=20, ge=8, le=50)
    RAG_RERANK_TOP_K: int = Field(default=4, ge=1, le=10)
    RAG_RERANK_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    RAG_RERANK_CIRCUIT_BREAKER_COOLDOWN_SECONDS: int = 30
    RAG_PLANNER_PROVIDER: str | None = None
    RAG_PLANNER_TIMEOUT_SECONDS: int = Field(default=8, ge=1, le=60)
    RAG_PLANNER_THINKING_ENABLED: bool = False
    RAG_PLANNER_REFUSAL_CONFIDENCE_THRESHOLD: float = Field(
        default=0.85, ge=0.0, le=1.0
    )
    RAG_PLANNER_REFUSAL_MESSAGE: str = "当前请求暂时无法可靠回答。"
    RAG_MIN_HIT_COUNT: int = Field(default=1, ge=1)
    RAG_MIN_RELEVANCE_SCORE: float = Field(default=0.2, ge=0.0, le=1.0)
    RAG_MIN_RERANK_SCORE: float = Field(default=4.0, ge=0.0, le=10.0)
    RAG_REFUSAL_MESSAGE: str = "知识库中没有找到足够相关的信息，暂时无法基于资料回答。"
    RAG_HYBRID_MIN_SOURCE_SCORE: float = Field(default=0.3, ge=0.0, le=1.0)

    # ── External Context Retrieval ────────────────────────────────
    EXTERNAL_CONTEXT_PROVIDER: str = "tavily"
    EXTERNAL_CONTEXT_TOP_K: int = Field(default=4, ge=1, le=10)
    EXTERNAL_CONTEXT_TIMEOUT_SECONDS: int = Field(default=6, ge=1, le=30)
    EXTERNAL_CONTEXT_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    EXTERNAL_CONTEXT_CIRCUIT_BREAKER_COOLDOWN_SECONDS: int = 30
    TAVILY_API_KEY: str | None = None
    TAVILY_BASE_URL: str = "https://api.tavily.com"

    # ── RAG Embedding ─────────────────────────────────────────────
    RAG_EMBED_PROVIDER: str = "dashscope"
    RAG_EMBED_BASE_URL: str | None = None
    RAG_EMBED_API_KEY: str | None = None
    RAG_EMBED_DIM: int = Field(default=768, ge=1)
    RAG_EMBED_BATCH_SIZE: int = Field(default=10, ge=1, le=256)

    # ── Knowledge Chunking ────────────────────────────────────────
    KNOWLEDGE_CHUNK_SIZE: int = 800
    KNOWLEDGE_CHUNK_OVERLAP: int = 120
    KNOWLEDGE_MAX_UPLOAD_SIZE_MB: int = 20
    KNOWLEDGE_INGEST_STALE_TIMEOUT_SECONDS: int = Field(default=1800, ge=60)

    # ── Search Text ───────────────────────────────────────────────
    SEARCH_TEXT_DEFAULT_TOKEN_LIMIT: int = 60
    SEARCH_TEXT_KEYWORD_TOKEN_LIMIT: int = 30
    SEARCH_TEXT_KEYWORD_REPEAT: int = 2

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


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()


ai_settings = get_ai_settings()
