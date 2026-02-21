import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- 目录配置 ---
    # 使用 Path 的写法更现代、简洁
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    LOG_DIR: Path = BASE_DIR / "logs/backend"

    # --- 项目信息 ---
    PROJECT_NAME: str = "Obsidian Mentor AI"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # --- 数据库配置 (敏感信息不设置默认值，强制从 env 读取) ---
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_SERVER: str = "postgres1"  # 默认值可以保留，env 有则覆盖
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "mentor_ai"
    POSTGRES_DB_ECHO: bool = False  # 生产环境建议关闭，开发环境可开启

    BATCH_SIZE: int = 500

    # --- LLM & AI 配置 ---
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

    OBSIDIAN_VAULT_PATH: str = "/data/obsidian"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
