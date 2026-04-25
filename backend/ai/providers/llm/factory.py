from backend.core.config import settings
from backend.domain.interfaces import AbstractLLMService

from .llm_service import LLMService
from .mock_provider import MockLLMService
from .pydantic_ai_service import PydanticAILLMService


class LLMProviderFactory:
    """负责按配置选择并构建 LLM provider。"""

    @staticmethod
    def create(provider: str | None = None) -> AbstractLLMService:
        normalized = (provider or settings.LLM_PROVIDER).strip().lower()
        if normalized in {"mock", "mock-llm", "fake"}:
            return MockLLMService()
        if normalized in {"openai", "openai-compatible", "external-api"}:
            return LLMService(provider_name=normalized)
        deepseek_models = {
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        }
        if normalized == "deepseek" or normalized in deepseek_models:
            model_name = (
                normalized
                if normalized in deepseek_models
                else settings.DEEPSEEK_MODEL_NAME
            )
            return LLMService(
                provider_name="deepseek",
                base_url=settings.DEEPSEEK_BASE_URL,
                api_key=settings.DEEPSEEK_API_KEY or settings.LLM_API_KEY,
                model_name=model_name,
            )
        if normalized in {"pydantic-ai", "pydantic_ai", "gemini", "google", "google-gla"}:
            return PydanticAILLMService()
        raise ValueError(f"Unsupported LLM provider: {provider or settings.LLM_PROVIDER}")
