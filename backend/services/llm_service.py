"""
LLM Service — 大语言模型调用封装

企业级设计：
- 统一的错误处理与日志
- 流式 / 非流式两种调用模式
- 通过 LLMQueryDTO / LLMResultDTO 与上层解耦
- 模型配置由 config 驱动，不再硬编码
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator

import openai

from backend.core.config import settings
from backend.core.exceptions import ServiceError
from backend.domain.interfaces import AbstractLLMService
from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO
from backend.utils.tokenizer import count_messages_tokens, count_tokens

logger = logging.getLogger(__name__)


class LLMService(AbstractLLMService):
    """LLM 服务：处理大语言模型 API 调用"""

    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        """
        流式返回 LLM 响应 (使用异步客户端)
        """
        logger.info("LLM 开始流式请求: session_id=%s", query.session_id)
        try:
            if query.conversation_history:
                messages = query.conversation_history
            else:
                messages = [{"role": "user", "content": query.query_text}]

            client = openai.AsyncOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
            )

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
