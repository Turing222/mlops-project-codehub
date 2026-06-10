"""Pydantic AI LLM service.

职责：通过 Pydantic AI 统一适配 Google 与 OpenAI-compatible LLM provider。
边界：本模块不处理会话持久化或 Prompt 预算，业务输入输出保持 LLM DTO。
失败处理：依赖缺失、API key 缺失和 provider 异常会转换为统一业务错误。
"""

import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from backend.ai.providers.llm.pydantic_ai_models import create_pydantic_ai_model
from backend.config.ai_settings import ai_settings
from backend.config.llm import LLMProfile, get_llm_model_config
from backend.contracts.interfaces import AbstractLLMService
from backend.core.circuit_breaker import CircuitBreaker
from backend.core.exceptions import AppException, app_service_error
from backend.models.schemas.chat.dto import (
    ConversationMessage,
    LLMQueryDTO,
    LLMResultDTO,
)
from backend.observability.trace_utils import (
    build_llm_span_attributes,
    set_span_attributes,
    trace_span,
)
from backend.utils.token_estimation import estimate_tokens

logger = logging.getLogger(__name__)

_ROLE_LABELS = {
    "user": "用户",
    "assistant": "助手",
}


class PydanticAILLMService(AbstractLLMService):
    """Pydantic AI provider 的 LLM 服务适配器。"""

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def __init__(
        self,
        *,
        profile: LLMProfile | None = None,
        provider_name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        max_retries: int | None = None,
        extra_body: dict[str, object] | None = None,
        circuit_breaker_failure_threshold: int | None = None,
        circuit_breaker_cooldown_seconds: int | None = None,
    ) -> None:
        resolved_profile = profile or get_llm_model_config().resolve_profile(
            provider_name or "deepseek"
        )
        self.profile = (
            resolved_profile
            if base_url is None and model_name is None
            else LLMProfile(
                name=resolved_profile.name,
                provider=provider_name or resolved_profile.provider,
                model=model_name or resolved_profile.model,
                base_url=(
                    base_url
                    if base_url is not None
                    else resolved_profile.resolve_base_url()
                ),
                api_key_envs=resolved_profile.api_key_envs,
                aliases=resolved_profile.aliases,
                extra_body=resolved_profile.extra_body,
            )
        )
        self._provider_name = provider_name or self.profile.provider
        self.api_key = (
            api_key if api_key is not None else self.profile.resolve_api_key()
        )
        self._model_name = self.profile.model
        self.max_retries = max_retries
        self._extra_body = (
            extra_body if extra_body is not None else self.profile.extra_body
        )
        self._circuit = CircuitBreaker(
            name="llm",
            failure_threshold=(
                circuit_breaker_failure_threshold
                or ai_settings.LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD
            ),
            cooldown_seconds=(
                circuit_breaker_cooldown_seconds
                or ai_settings.LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS
            ),
        )

    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        logger.info("Pydantic AI 开始流式请求: session_id=%s", query.session_id)
        try:
            instructions, prompt = self._build_agent_input(query)
            with trace_span(
                "llm.pydantic_ai.stream",
                {
                    **build_llm_span_attributes(
                        provider=self.provider_name,
                        model=self.model_name,
                        operation="generate",
                        stream=True,
                    ),
                    "chat.session_id": query.session_id,
                    "llm.stream": True,
                    "llm.prompt.char_count": len(prompt),
                    "llm.instructions.present": instructions is not None,
                },
            ) as span:
                agent = self._create_agent(instructions)
                await self._circuit.acquire()
                chunk_count = 0
                char_count = 0

                async with agent.run_stream(
                    prompt,
                    model_settings=_build_model_settings(
                        _merge_extra_body(self._extra_body, query.extra_body)
                    ),
                ) as result:
                    await self._circuit.on_success()
                    async for delta in result.stream_text(delta=True):
                        if delta:
                            chunk_count += 1
                            char_count += len(delta)
                            yield delta
                set_span_attributes(
                    span,
                    {
                        "llm.response.chunk_count": chunk_count,
                        "llm.response.char_count": char_count,
                    },
                )

            logger.info("Pydantic AI 流式请求完成: session_id=%s", query.session_id)
        except AppException:
            raise
        except Exception as exc:
            await self._circuit.on_failure()
            logger.error(
                "Pydantic AI 流式请求失败: session_id=%s, error=%s",
                query.session_id,
                str(exc),
                exc_info=True,
            )
            raise app_service_error(
                "LLM 服务调用失败",
                code="LLM_SERVICE_ERROR",
                details={"session_id": str(query.session_id), "error": str(exc)},
            ) from exc

    async def generate_response(
        self,
        query: LLMQueryDTO,
    ) -> LLMResultDTO:
        logger.info("Pydantic AI 开始非流式请求: session_id=%s", query.session_id)
        start = time.perf_counter()

        try:
            instructions, prompt = self._build_agent_input(query)
            with trace_span(
                "llm.pydantic_ai.generate",
                {
                    **build_llm_span_attributes(
                        provider=self.provider_name,
                        model=self.model_name,
                        operation="generate",
                        stream=False,
                    ),
                    "chat.session_id": query.session_id,
                    "llm.stream": False,
                    "llm.prompt.char_count": len(prompt),
                    "llm.instructions.present": instructions is not None,
                },
            ) as span:
                agent = self._create_agent(instructions)
                await self._circuit.acquire()
                result = await agent.run(
                    prompt,
                    model_settings=_build_model_settings(
                        _merge_extra_body(self._extra_body, query.extra_body)
                    ),
                )
                await self._circuit.on_success()

                content = str(getattr(result, "output", ""))
                latency_ms = int((time.perf_counter() - start) * 1000)
                prompt_tokens, completion_tokens = _usage_tokens(result)
                if completion_tokens is None:
                    completion_tokens = estimate_tokens(content, self.model_name)
                set_span_attributes(
                    span,
                    {
                        "llm.response.char_count": len(content),
                        "llm.response.prompt_tokens": prompt_tokens,
                        "llm.response.completion_tokens": completion_tokens,
                        "llm.latency_ms": latency_ms,
                        "gen_ai.usage.input_tokens": prompt_tokens,
                        "gen_ai.usage.output_tokens": completion_tokens,
                    },
                )
        except AppException:
            raise
        except Exception as exc:
            await self._circuit.on_failure()
            logger.error(
                "Pydantic AI 非流式请求失败: session_id=%s, error=%s",
                query.session_id,
                str(exc),
                exc_info=True,
            )
            raise app_service_error(
                "LLM 服务调用失败",
                code="LLM_SERVICE_ERROR",
                details={"session_id": str(query.session_id), "error": str(exc)},
            ) from exc

        return LLMResultDTO(
            content=content,
            latency_ms=latency_ms,
            success=True,
            error_message=None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _create_agent(self, instructions: str | None):
        try:
            from pydantic_ai import Agent
        except ImportError as exc:
            raise app_service_error(
                "Pydantic AI 未安装",
                code="PYDANTIC_AI_MISSING",
                details={"install": 'uv add "pydantic-ai-slim[google,openai]"'},
            ) from exc

        model = create_pydantic_ai_model(
            profile=self.profile,
            api_key=self.api_key,
            max_retries=self.max_retries,
        )
        return Agent(
            model,
            instructions=instructions,
            instrument=True,
            name="llm",
        )

    @classmethod
    def _build_agent_input(cls, query: LLMQueryDTO) -> tuple[str | None, str]:
        fallback_message: ConversationMessage = {
            "role": "user",
            "content": query.query_text,
        }
        messages: list[ConversationMessage] = query.conversation_history or [
            fallback_message
        ]
        system_parts = [
            message["content"].strip()
            for message in messages
            if message["role"] == "system" and message["content"].strip()
        ]
        dialogue = [message for message in messages if message["role"] != "system"]

        if dialogue and dialogue[-1]["role"] == "user":
            current_query = dialogue[-1]["content"]
            prior_messages = dialogue[:-1]
        else:
            current_query = query.query_text
            prior_messages = dialogue

        prompt = cls._build_prompt(
            current_query=current_query, prior_messages=prior_messages
        )
        instructions = "\n\n".join(system_parts) if system_parts else None
        return instructions, prompt

    @classmethod
    def _build_prompt(
        cls,
        *,
        current_query: str,
        prior_messages: list[ConversationMessage],
    ) -> str:
        if not prior_messages:
            return current_query

        history_lines: list[str] = []
        for message in prior_messages:
            role_label = _ROLE_LABELS.get(message["role"], message["role"])
            content = message["content"].strip()
            if content:
                history_lines.append(f"{role_label}: {content}")

        if not history_lines:
            return current_query

        history = "\n".join(history_lines)
        return f"以下是对话历史（按时间顺序）：\n{history}\n\n当前用户问题：\n{current_query}"


def _merge_extra_body(
    profile_body: dict[str, object] | None,
    request_body: dict[str, object] | None,
) -> dict[str, object] | None:
    if profile_body is None and request_body is None:
        return None
    if profile_body is None:
        return dict(request_body)  # type: ignore[arg-type]
    if request_body is None:
        return dict(profile_body)
    return {**profile_body, **request_body}


def _build_model_settings(extra_body: dict[str, object] | None):
    if extra_body is None:
        return None
    from pydantic_ai.settings import ModelSettings

    return ModelSettings(extra_body=extra_body)


def _usage_tokens(result: Any) -> tuple[int | None, int | None]:
    usage_value = getattr(result, "usage", None)
    if callable(usage_value):
        usage_value = usage_value()
    if usage_value is None:
        return None, None

    prompt_tokens = getattr(usage_value, "request_tokens", None)
    completion_tokens = getattr(usage_value, "response_tokens", None)
    if prompt_tokens is None:
        prompt_tokens = getattr(usage_value, "prompt_tokens", None)
    if completion_tokens is None:
        completion_tokens = getattr(usage_value, "completion_tokens", None)
    return prompt_tokens, completion_tokens
