import asyncio
import logging
from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


class LLMService:
    """LLM 服务：处理大语言模型 API 调用"""

    async def stream_response(
        self,
        query_text: str,
        session_id: str | None = None,
        conversation_history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式返回 LLM 响应

        Args:
            query_text: 用户问题
            session_id: 会话 ID（用于上下文关联）
            conversation_history: 历史对话记录

        Yields:
            流式响应的文本片段
        """
        # TODO: 实际项目中替换为真实的 LLM API 调用
        # 例如：OpenAI, Claude, Azure OpenAI, 本地模型等

        mock_response = self._generate_mock_response(query_text)

        # 模拟流式输出：每个字符逐个返回
        for i, char in enumerate(mock_response):
            yield char
            # 模拟网络延迟
            if (i + 1) % 10 == 0:
                await self._sleep(0.01)

    async def generate_response(
        self,
        query_text: str,
        session_id: str | None = None,
        conversation_history: list[dict] | None = None,
    ) -> str:
        """
        非流式返回完整响应

        Returns:
            完整的 LLM 响应文本
        """
        # 收集所有流式输出
        chunks = []
        async for chunk in self.stream_response(
            query_text, session_id, conversation_history
        ):
            chunks.append(chunk)
        return "".join(chunks)

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
