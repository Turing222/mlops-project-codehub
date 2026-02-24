import asyncio
import time
from unittest.mock import AsyncMock, patch
from backend.services.llm_service import LLMService
from backend.models.schemas.chat_schema import LLMQueryDTO
from backend.core.config import settings

async def test_llm_concurrency():
    # 模拟 settings.LLM_MAX_CONCURRENCY = 2
    with patch("backend.services.llm_service.settings.LLM_MAX_CONCURRENCY", 2):
        # 强制重置信号量（因为它是类变量且已经被初始化）
        LLMService._semaphore = asyncio.Semaphore(2)
        service = LLMService()
        
        # 模拟 AsyncOpenAI
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_cm = AsyncMock()
            
            # 模拟流式返回，每个请求耗时 0.5s
            async def mock_stream(*args, **kwargs):
                await asyncio.sleep(0.5)
                yield MagicChunk("chunk1")
                yield MagicChunk("chunk2")
                
            mock_client.chat.completions.create = AsyncMock(side_effect=mock_stream)
            
            import uuid
            query = LLMQueryDTO(session_id=uuid.uuid4(), query_text="hello", conversation_history=[])
            
            start_time = time.time()
            # 同时发起 4 个请求
            tasks = [service.generate_response(query) for _ in range(4)]
            results = await asyncio.gather(*tasks)
            end_time = time.time()
            
            total_time = end_time - start_time
            print(f"Total time for 4 requests with concurrency 2: {total_time:.2f}s")
            
            # 预期时间应该是大约 1.0s (2组并发，每组0.5s)
            assert 0.9 <= total_time <= 1.5
            assert len(results) == 4
            assert all(r.success for r in results)

class MagicChunk:
    def __init__(self, content):
        self.choices = [Choice(content)]

class Choice:
    def __init__(self, content):
        self.delta = Delta(content)

class Delta:
    def __init__(self, content):
        self.content = content

if __name__ == "__main__":
    asyncio.run(test_llm_concurrency())
