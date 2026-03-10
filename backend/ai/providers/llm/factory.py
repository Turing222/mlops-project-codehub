from backend.core.config import settings
from backend.domain.interfaces import AbstractLLMService

from .llm_service import LLMService
from .mock_provider import MockLLMService


class LLMProviderFactory:
    """负责按配置选择并构建 LLM provider。"""

    @staticmethod
    def create(provider: str | None = None) -> AbstractLLMService:
        normalized = (provider or settings.LLM_PROVIDER).strip().lower()
        if normalized in {"mock", "mock-llm", "fake"}:
            return MockLLMService()
        if normalized in {"openai", "openai-compatible", "ollama"}:
            return LLMService()
        raise ValueError(f"Unsupported LLM provider: {provider or settings.LLM_PROVIDER}")
