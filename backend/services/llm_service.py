"""
LLM Service — 大语言模型调用封装

企业级设计：
- 统一的错误处理与日志
- 流式 / 非流式两种调用模式
- 通过 LLMQueryDTO / LLMResultDTO 与上层解耦
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator

import openai

from backend.core.exceptions import ServiceError
from backend.domain.interfaces import AbstractLLMService
from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO

logger = logging.getLogger(__name__)


class LLMService(AbstractLLMService):
    """LLM 服务：处理大语言模型 API 调用"""

    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        """
        流式返回 LLM 响应

        Args:
            query: LLM 查询 DTO

        Yields:
            流式响应的文本片段

        Raises:
            ServiceError: LLM 调用失败
        """
        logger.info(
            "LLM 流式请求开始: session_id=%s, query_len=%d",
            query.session_id,
            len(query.query_text),
        )
        try:
            # TODO: 实际项目中替换为真实的 LLM API 调用
            # 例如：OpenAI, Claude, Azure OpenAI, 本地模型等
            # mock_response = self._generate_mock_response(query.query_text)
            client = openai.OpenAI(
                base_url="http://win.host:11434/v1", api_key="ollama"
            )
            response = response = client.chat.completions.create(
                model="qwen2.5:latest",
                messages=[{"role": "user", "content": query.query_text}],
                stream=True,
            )
            full_response_content = []

            for chunk in response:
                # 注意：有的 chunk 可能是空的（比如开始或结束的信号），需要判断
                content = chunk.choices[0].delta.content
                if content:
                    print(content, end="", flush=True)  # 实时打印到终端
                    full_response_content.append(content)
                    yield content  # 流式返回给调用方

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
        非流式返回完整响应

        Args:
            query: LLM 查询 DTO

        Returns:
            LLMResultDTO 包含完整响应和性能指标
        """
        logger.info(
            "LLM 非流式请求开始: session_id=%s, query_len=%d",
            query.session_id,
            len(query.query_text),
        )
        start_time = time.time()

        try:
            chunks: list[str] = []
            async for chunk in self.stream_response(query):
                chunks.append(chunk)

            content = "".join(map(str, chunks))
            latency_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "LLM 非流式请求完成: session_id=%s, content_len=%d, latency_ms=%d",
                query.session_id,
                len(content),
                latency_ms,
            )
            return LLMResultDTO(
                content=content,
                latency_ms=latency_ms,
                success=True,
            )
        except ServiceError:
            # ServiceError 已在 stream_response 中记录日志，直接抛出
            raise
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "LLM 非流式请求异常: session_id=%s, latency_ms=%d, error=%s",
                query.session_id,
                latency_ms,
                str(e),
                exc_info=True,
            )
            return LLMResultDTO(
                content="",
                latency_ms=latency_ms,
                success=False,
                error_message=str(e),
            )

    def _generate_mock_response(self, query_text: str) -> str:
        """
        生成 Mock LLM 响应
        实际项目中这里应该调用真实的 LLM API
        """
        responses = [
            f'这是一个模拟的 AI 回复。您的问题是："{query_text[:30]}..."\n\n',
            "在实际项目中，这里会调用真实的 LLM API（如 OpenAI、Claude 等）。\n\n",
            "当前使用的是 Mock 模式，用于演示流式输出的效果。\n\n",
            "每个字符会逐个返回，模拟真实的流式响应体验。\n\n",
            "您可以继续提问，我会继续以流式方式回复您。",
        ]
        return "".join(responses)

    async def _sleep(self, seconds: float):
        """异步休眠，用于模拟延迟"""
        await asyncio.sleep(seconds)
