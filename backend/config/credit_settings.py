"""Credit application settings.

职责：管理 Credits 账户、签到、以及大模型消耗折算费率等配置。
边界：不包含 Web/DB/Redis/Auth 等基础设施配置，与 AI/RAG 配置隔离。
副作用：导入时加载 *_FILE secret 到环境变量。
"""

import logging
from functools import lru_cache

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from backend.config.ai_settings import (
    AppYamlSettingsSource,
    _env_files,
)

_logger = logging.getLogger(__name__)


class CreditSettings(BaseSettings):
    """Credits 系统相关配置。"""

    CREDIT_DAILY_CHECKIN_AMOUNT: int = 100
    CREDIT_DAILY_CHECKIN_VALID_DAYS: int = 7
    CREDIT_TO_TOKEN_RATIO: float = 100.0
    CREDIT_MINIMUM_ESTIMATED_COST: int = 10
    """Minimum estimated cost for credit pre-check before LLM generation."""

    CREDIT_ESTIMATED_OUTPUT_TOKENS: int = 512
    """Estimated output tokens for credit pre-check cost calculation."""

    CREDIT_MODEL_RATES: dict[str, dict[str, float]] = {
        "default": {"input": 1.0, "output": 2.0},
        # OpenAI
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "gpt-4": {"input": 10.0, "output": 30.0},
        "gpt-3.5-turbo": {"input": 1.5, "output": 2.0},
        # DeepSeek
        "deepseek-chat": {"input": 1.0, "output": 2.0},
        "deepseek-v4-flash": {"input": 0.5, "output": 1.0},
        "deepseek-v4-pro": {"input": 2.0, "output": 8.0},
        # Gemini
        "gemini-2.5-flash": {"input": 0.15, "output": 0.6},
        # Bifrost gateway passthrough (deepseek/deepseek-chat)
        "deepseek/deepseek-chat": {"input": 1.0, "output": 2.0},
    }

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
def get_credit_settings() -> CreditSettings:
    return CreditSettings()


credit_settings = get_credit_settings()
