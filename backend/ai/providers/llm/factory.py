from backend.config.llm import LLMProfile, get_llm_model_config
from backend.core.config import settings
from backend.domain.interfaces import AbstractLLMService

from .llm_service import LLMService
from .mock_provider import MockLLMService
from .pydantic_ai_service import PydanticAILLMService
from .routing_service import LLMRouteCandidate, LLMRoutingService


class LLMProviderFactory:
    """负责按配置选择并构建 LLM provider。"""

    @staticmethod
    def create(provider: str | None = None) -> AbstractLLMService:
        model_config = get_llm_model_config()
        profiles = model_config.resolve_route(provider or settings.LLM_PROVIDER)

        expanded_profiles: list[tuple[LLMProfile, str | None, int]] = []
        for profile in profiles:
            api_keys = profile.resolve_api_keys() or (None,)
            expanded_profiles.extend(
                (profile, api_key, key_index)
                for key_index, api_key in enumerate(api_keys, start=1)
            )

        use_route = len(expanded_profiles) > 1
        candidates: list[LLMRouteCandidate] = []
        for profile, api_key, key_index in expanded_profiles:
            service = LLMProviderFactory._create_profile_service(
                profile=profile,
                api_key=api_key,
                max_retries=0 if use_route else None,
            )
            candidates.append(
                LLMRouteCandidate(
                    label=_candidate_label(profile.provider, profile.model, key_index),
                    service=service,
                )
            )

        if len(candidates) == 1:
            return candidates[0].service

        return LLMRoutingService(candidates)

    @staticmethod
    def _create_profile_service(
        *,
        profile: LLMProfile,
        api_key: str | None,
        max_retries: int | None,
    ) -> AbstractLLMService:
        normalized_provider = profile.provider.strip().lower()

        if normalized_provider == "mock":
            return MockLLMService()

        if normalized_provider in {"openai", "openai-compatible"}:
            return LLMService(
                provider_name=profile.provider,
                base_url=profile.resolve_base_url(),
                api_key=api_key,
                model_name=profile.model,
                max_retries=max_retries,
            )

        if normalized_provider == "deepseek":
            return LLMService(
                provider_name=profile.provider,
                base_url=profile.resolve_base_url(),
                api_key=api_key,
                model_name=profile.model,
                max_retries=max_retries,
            )

        if normalized_provider in {"pydantic-ai", "pydantic_ai", "gemini", "google"}:
            return PydanticAILLMService(
                api_key=api_key,
                model_name=profile.model,
            )

        raise ValueError(f"Unsupported LLM provider: {profile.provider}")


def _candidate_label(provider: str, model: str, key_index: int) -> str:
    return f"{provider}/{model}#key{key_index}"
