import asyncio
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from backend.ai.providers.llm.llm_service import LLMService
from backend.models.schemas.chat_schema import LLMQueryDTO

pytestmark = [pytest.mark.asyncio, pytest.mark.performance]


async def test_llm_concurrency():
    with patch("backend.ai.providers.llm.llm_service.settings.LLM_MAX_CONCURRENCY", 2):
        LLMService._semaphore = asyncio.Semaphore(2)
        service = LLMService()

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = mock_client_class.return_value

            async def mock_stream(*args, **kwargs):
                await asyncio.sleep(0.5)
                yield MagicChunk("chunk1")
                yield MagicChunk("chunk2")

            mock_client.chat.completions.create = AsyncMock(side_effect=mock_stream)

            query = LLMQueryDTO(session_id=uuid.uuid4(), query_text="hello", conversation_history=[])

            start_time = time.time()
            tasks = [service.generate_response(query) for _ in range(4)]
            results = await asyncio.gather(*tasks)
            end_time = time.time()

            total_time = end_time - start_time
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
