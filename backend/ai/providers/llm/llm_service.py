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

import openai
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from backend.ai.core.token_counter import count_tokens
from backend.core.config import settings
from backend.core.exceptions import ServiceError
from backend.domain.interfaces import AbstractLLMService
from backend.models.schemas.chat_schema import (
    ConversationMessage,
    LLMQueryDTO,
    LLMResultDTO,
)

logger = logging.getLogger(__name__)


class LLMService(AbstractLLMService):
    """LLM 服务：处理大语言模型 API 调用"""

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

    @staticmethod
    def _create_client() -> openai.AsyncOpenAI:
        return openai.AsyncOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
        )

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
            client = self._create_client()

            response = await client.chat.completions.create(
                model=settings.LLM_MODEL_NAME,
                messages=messages,
                stream=True,
            )

            async for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield content

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
        completion_tokens = count_tokens(content, settings.LLM_MODEL_NAME)

        return LLMResultDTO(
            content=content,
            latency_ms=latency_ms,
            success=True,
            error_message=None,
            prompt_tokens=None,
            completion_tokens=completion_tokens,
        )
