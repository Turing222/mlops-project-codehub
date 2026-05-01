"""Pydantic AI Gemini LLM service.

职责：通过 Pydantic AI 的 Google/Gemini provider 提供 LLM 调用能力。
边界：本模块只适配 Gemini 输入形态，不处理会话持久化或 Prompt 预算。
失败处理：依赖缺失、API key 缺失和 provider 异常会转换为统一业务错误。
"""

import logging
import time
from collections.abc import AsyncGenerator

from backend.ai.core.token_counter import count_tokens
from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractLLMService
from backend.core.exceptions import AppException, app_service_error
from backend.models.schemas.chat_schema import (
    ConversationMessage,
    LLMQueryDTO,
    LLMResultDTO,
)
from backend.observability.trace_utils import set_span_attributes, trace_span

logger = logging.getLogger(__name__)

_ROLE_LABELS = {
    "user": "用户",
    "assistant": "助手",
}


class PydanticAILLMService(AbstractLLMService):
    """Gemini provider 的 LLM 服务适配器。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
    ) -> None:
        profile = get_llm_model_config().resolve_profile("gemini")
        self.api_key = (
            api_key
            if api_key is not None
            else profile.resolve_api_key()
            or settings.GEMINI_API_KEY
            or settings.GOOGLE_API_KEY
        )
        self.model_name = model_name or profile.model

    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        logger.info("Pydantic AI Gemini 开始流式请求: session_id=%s", query.session_id)
        try:
            instructions, prompt = self._build_agent_input(query)
            with trace_span(
                "llm.gemini.stream",
                {
                    "gen_ai.system": "gemini",
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": self.model_name,
                    "chat.session_id": query.session_id,
                    "llm.stream": True,
                    "llm.prompt.char_count": len(prompt),
                    "llm.instructions.present": instructions is not None,
                },
            ) as span:
                agent = self._create_agent(instructions)
                chunk_count = 0
                char_count = 0

                async with agent.run_stream(prompt) as result:
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

            logger.info(
                "Pydantic AI Gemini 流式请求完成: session_id=%s", query.session_id
            )
        except AppException:
            raise
        except Exception as exc:
            logger.error(
                "Pydantic AI Gemini 流式请求失败: session_id=%s, error=%s",
                query.session_id,
                str(exc),
                exc_info=True,
            )
            raise app_service_error(
                "Gemini 服务调用失败",
                code="GEMINI_SERVICE_ERROR",
                details={"session_id": str(query.session_id), "error": str(exc)},
            ) from exc

    async def generate_response(
        self,
        query: LLMQueryDTO,
    ) -> LLMResultDTO:
        logger.info(
            "Pydantic AI Gemini 开始非流式请求: session_id=%s", query.session_id
        )
        start = time.perf_counter()

        try:
            instructions, prompt = self._build_agent_input(query)
            with trace_span(
                "llm.gemini.generate",
                {
                    "gen_ai.system": "gemini",
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": self.model_name,
                    "chat.session_id": query.session_id,
                    "llm.stream": False,
                    "llm.prompt.char_count": len(prompt),
                    "llm.instructions.present": instructions is not None,
                },
            ) as span:
                agent = self._create_agent(instructions)
                result = await agent.run(prompt)
        except AppException:
            raise
        except Exception as exc:
            logger.error(
                "Pydantic AI Gemini 非流式请求失败: session_id=%s, error=%s",
                query.session_id,
                str(exc),
                exc_info=True,
            )
            raise app_service_error(
                "Gemini 服务调用失败",
                code="GEMINI_SERVICE_ERROR",
                details={"session_id": str(query.session_id), "error": str(exc)},
            ) from exc

        content = str(getattr(result, "output", ""))
        latency_ms = int((time.perf_counter() - start) * 1000)
        completion_tokens = count_tokens(content, self.model_name)
        set_span_attributes(
            span,
            {
                "llm.response.char_count": len(content),
                "llm.response.completion_tokens": completion_tokens,
                "llm.latency_ms": latency_ms,
            },
        )

        return LLMResultDTO(
            content=content,
            latency_ms=latency_ms,
            success=True,
            error_message=None,
            prompt_tokens=None,
            completion_tokens=completion_tokens,
        )

    def _create_agent(self, instructions: str | None):
        if not self.api_key:
            raise app_service_error(
                "Gemini API Key 未配置",
                code="GEMINI_API_KEY_MISSING",
                details={"env": "GEMINI_API_KEY 或 GOOGLE_API_KEY"},
            )

        try:
            from pydantic_ai import Agent
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google import GoogleProvider
        except ImportError as exc:
            raise app_service_error(
                "Pydantic AI Gemini provider 未安装",
                code="GEMINI_PROVIDER_MISSING",
                details={"install": 'uv add "pydantic-ai-slim[google]"'},
            ) from exc

        provider = GoogleProvider(api_key=self.api_key)
        model = GoogleModel(self.model_name, provider=provider)
        return Agent(
            model,
            instructions=instructions,
            instrument=True,
            name="gemini_llm",
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
