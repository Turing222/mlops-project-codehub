import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- 目录配置 ---
    # 使用 Path 的写法更现代、简洁
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    LOG_DIR: Path = BASE_DIR / "logs/backend"

    # --- 项目信息 ---
    PROJECT_NAME: str = "Obsidian Mentor AI"
    VERSION: str = "0.1.0"
    API_ROOT_PATH: str = "/api"
    API_V1_STR: str = "/v1"

    # --- 数据库配置 (敏感信息不设置默认值，强制从 env 读取) ---
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_SERVER: str = "postgres1"  # 默认值可以保留，env 有则覆盖
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "mentor_ai"
    POSTGRES_DB_ECHO: bool = False  # 生产环境建议关闭，开发环境可开启
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20

    BATCH_SIZE: int = 500

    # --- LLM & AI 配置 ---
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

    OBSIDIAN_VAULT_PATH: str = "/data/obsidian"
    KNOWLEDGE_STORAGE_ROOT: Path = Path(".files/knowledge_files")
    KNOWLEDGE_MAX_UPLOAD_SIZE_MB: int = 20
    KNOWLEDGE_CHUNK_SIZE: int = 800
    KNOWLEDGE_CHUNK_OVERLAP: int = 120

    # --- Redis 配置 ---
    REDIS_URL: str | None = None
    TASKIQ_REDIS_URL: str | None = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None

    # --- 并发控制配置 ---
    LLM_MAX_CONCURRENCY: int = 5
    DB_MAX_CONCURRENCY: int = 10

    # --- LLM 对话配置 ---
    LLM_PROVIDER: str = "mock"
    LLM_MODEL_NAME: str = "qwen2.5:latest"
    LLM_BASE_URL: str = "http://win.host:11434/v1"
    LLM_API_KEY: str = "ollama"
    LLM_MAX_CONTEXT_TOKENS: int = 4096
    LLM_MAX_HISTORY_ROUNDS: int = 10
    LLM_RESERVED_RESPONSE_TOKENS: int = 1024
    CHAT_MEMORY_RECENT_ROUNDS: int = 6
    CHAT_MEMORY_SUMMARY_MAX_CHARS: int = 1500
    CHAT_MEMORY_SNIPPET_CHARS: int = 120
    CHAT_MEMORY_FETCH_LIMIT: int = 2000
    RAG_TOP_K: int = 4
    RAG_EMBED_PROVIDER: str = "openai-compatible"
    RAG_EMBED_MODEL_NAME: str = "text-embedding-3-small"
    RAG_EMBED_BASE_URL: str | None = None
    RAG_EMBED_API_KEY: str | None = None
    RAG_EMBED_DIM: int = 768
    RAG_EMBED_DEVICE: str = "cpu"

    # --- 安全配置 (SECRET_KEY 必须从 env 读取) ---
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Pydantic Settings 配置
    model_config = SettingsConfigDict(
        env_file=".env" if os.path.exists(".env") else None,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
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
        return urlunsplit((parsed.scheme, parsed.netloc, f"/{db}", parsed.query, parsed.fragment))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
