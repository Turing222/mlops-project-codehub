"""Mock LLM provider.

职责：为本地开发、烟测和压测提供确定性的 LLM 输出。
边界：本模块不发起外部网络请求，也不模拟真实模型质量。
副作用：通过 sleep 模拟流式延迟，便于观察 API/DB/Redis 链路压力。
"""

import asyncio
from collections.abc import AsyncGenerator

from backend.core.trace_utils import set_span_attributes, trace_span
from backend.domain.interfaces import AbstractLLMService
from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO


class MockLLMService(AbstractLLMService):
    """用于本地和压测的确定性 LLM 实现。"""
    
    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        with trace_span(
            "llm.mock.stream",
            {
                "gen_ai.system": "mock",
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "mock",
                "chat.session_id": query.session_id,
                "llm.stream": True,
            },
        ) as span:
            await asyncio.sleep(0.2)

            fake_response = "这是一段由 MockLLMService 自动生成的测试回复，用于极限压测场景，没有任何实际意义。祝压测顺利！" * 3

            for char in fake_response:
                await asyncio.sleep(0.01)
                yield char
            set_span_attributes(
                span,
                {
                    "llm.response.chunk_count": len(fake_response),
                    "llm.response.char_count": len(fake_response),
                },
            )

    async def generate_response(
        self,
        query: LLMQueryDTO,
    ) -> LLMResultDTO:
        with trace_span(
            "llm.mock.generate",
            {
                "gen_ai.system": "mock",
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "mock",
                "chat.session_id": query.session_id,
                "llm.stream": False,
            },
        ) as span:
            await asyncio.sleep(1.0)

            fake_response = "这是非流式接口返回的测试数据。"
            set_span_attributes(
                span,
                {
                    "llm.response.char_count": len(fake_response),
                    "llm.response.completion_tokens": len(fake_response),
                },
            )
        return LLMResultDTO(
            success=True,
            content=fake_response,
            completion_tokens=len(fake_response),
            error_message=None,
        )
