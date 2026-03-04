import asyncio
from typing import AsyncGenerator

from backend.domain.interfaces import AbstractLLMService
from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO

class MockLLMService(AbstractLLMService):
    """
    专为极高并发压测设计的虚假 LLM 引擎。
    它不会发起任何真实的网络请求，而是通过 asyncio.sleep 模拟生成延迟，
    从而将性能瓶颈完全留给 FastAPI / 数据库 / Redis 进行检验。
    """
    
    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        # 1. 模拟网络往返握手延迟 (0.2 秒)
        await asyncio.sleep(0.2)
        
        # 2. 模拟大模型缓慢吐字的过程
        fake_response = "这是一段由 MockLLMService 自动生成的测试回复，用于极限压测场景，没有任何实际意义。祝压测顺利！" * 3
        
        for char in fake_response:
            await asyncio.sleep(0.01) # 模拟每个字 10 毫秒的生成时间
            yield char

    async def generate_response(
        self,
        query: LLMQueryDTO,
    ) -> LLMResultDTO:
        # 模拟全量生成的延迟
        await asyncio.sleep(1.0)
        
        fake_response = "这是非流式接口返回的测试数据。"
        return LLMResultDTO(
            success=True,
            content=fake_response,
            completion_tokens=len(fake_response), 
            error_message=None
        )
