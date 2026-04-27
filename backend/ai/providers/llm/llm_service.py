"""
LLM Service — 大语言模型调用封装

企业级设计：
- 统一的错误处理与日志
- 流式 / 非流式两种调用模式
- 通过 LLMQueryDTO / LLMResultDTO 与上层解耦
- 模型配置由 config 驱动，不再硬编码
"""

import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import openai
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from backend.ai.core.token_counter import count_tokens
from backend.config.llm import get_llm_model_config
from backend.core.config import settings
from backend.core.exceptions import ServiceError
from backend.core.trace_utils import set_span_attributes, trace_span
from backend.domain.interfaces import AbstractLLMService
from backend.models.schemas.chat_schema import (
    ConversationMessage,
    LLMQueryDTO,
    LLMResultDTO,
)

logger = logging.getLogger(__name__)


class LLMService(AbstractLLMService):
    """LLM 服务：处理大语言模型 API 调用"""

    def __init__(
        self,
        *,
        provider_name: str = "openai-compatible",
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        max_retries: int | None = None,
    ):
        profile = get_llm_model_config().resolve_profile(provider_name)
        self.provider_name = provider_name
        self.base_url = base_url or profile.resolve_base_url() or settings.LLM_BASE_URL
        self.api_key = (
            api_key if api_key is not None else profile.resolve_api_key() or settings.LLM_API_KEY
        )
        self.model_name = model_name or profile.model
        self.max_retries = max_retries
        self._client: openai.AsyncOpenAI | None = None

    @staticmethod
    def _to_openai_messages(
        messages: list[ConversationMessage],
    ) -> list[ChatCompletionMessageParam]:
        openai_messages: list[ChatCompletionMessageParam] = []

        for msg in messages:
            if msg["role"] == "system":
                system_message: ChatCompletionSystemMessageParam = {
                    "role": "system",
                    "content": msg["content"],
                }
                openai_messages.append(system_message)
            elif msg["role"] == "assistant":
                assistant_message: ChatCompletionAssistantMessageParam = {
                    "role": "assistant",
                    "content": msg["content"],
                }
                openai_messages.append(assistant_message)
            else:
                user_message: ChatCompletionUserMessageParam = {
                    "role": "user",
                    "content": msg["content"],
                }
                openai_messages.append(user_message)

        return openai_messages

    @staticmethod
    def _build_messages(query: LLMQueryDTO) -> list[ChatCompletionMessageParam]:
        if query.conversation_history:
            return LLMService._to_openai_messages(query.conversation_history)
        return [{"role": "user", "content": query.query_text}]

    def _create_client(self) -> openai.AsyncOpenAI:
        if not self.api_key:
            raise ServiceError(
                "LLM API Key 未配置",
                details={"provider": self.provider_name},
            )
        if self._client is None:
            client_kwargs: dict[str, Any] = {
                "base_url": self.base_url,
                "api_key": self.api_key,
            }
            if self.max_retries is not None:
                client_kwargs["max_retries"] = self.max_retries
            self._client = openai.AsyncOpenAI(**client_kwargs)
        return self._client

    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        """
        流式返回 LLM 响应 (使用异步客户端)
        """
        logger.info("LLM 开始流式请求: session_id=%s", query.session_id)
        try:
            messages = self._build_messages(query)
            with trace_span(
                "llm.openai_compatible.stream",
                {
                    "gen_ai.system": self.provider_name,
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": self.model_name,
                    "llm.base_url": self.base_url,
                    "chat.session_id": query.session_id,
                    "llm.messages.count": len(messages),
                    "llm.stream": True,
                },
            ) as span:
                client = self._create_client()

                response = await client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    stream=True,
                )

                chunk_count = 0
                char_count = 0
                async for chunk in response:
                    content = chunk.choices[0].delta.content
                    if content:
                        chunk_count += 1
                        char_count += len(content)
                        yield content
                set_span_attributes(
                    span,
                    {
                        "llm.response.chunk_count": chunk_count,
                        "llm.response.char_count": char_count,
                    },
                )

            logger.info("LLM 流式请求完成: session_id=%s", query.session_id)
        except Exception as e:
            logger.error(
                "LLM 流式请求失败: session_id=%s, error=%s",
                query.session_id,
                str(e),
                exc_info=True,
            )
            raise ServiceError(
                "LLM 服务调用失败",
                details={"session_id": str(query.session_id), "error": str(e)},
            ) from e

    async def generate_response(
        self,
        query: LLMQueryDTO,
    ) -> LLMResultDTO:
        """
        非流式返回 LLM 响应。
        内部复用流式路径并聚合结果，保持调用链一致。
        """
        start = time.perf_counter()
        chunks: list[str] = []

        try:
            with trace_span(
                "llm.openai_compatible.generate",
                {
                    "gen_ai.system": self.provider_name,
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": self.model_name,
                    "chat.session_id": query.session_id,
                    "llm.stream": False,
                },
            ) as span:
                async for chunk in self.stream_response(query):
                    chunks.append(chunk)
        except ServiceError:
            raise
        except Exception as e:
            logger.error(
                "LLM 非流式请求失败: session_id=%s, error=%s",
                query.session_id,
                str(e),
                exc_info=True,
            )
            raise ServiceError(
                "LLM 服务调用失败",
                details={"session_id": str(query.session_id), "error": str(e)},
            ) from e

        content = "".join(chunks)
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
