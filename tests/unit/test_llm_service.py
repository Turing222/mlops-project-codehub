"""
LLMService 单元测试

覆盖 LLMService 的流式与非流式响应逻辑。
Mock 内部的 _sleep 方法来加速测试执行。
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO
from backend.services.llm_service import LLMService

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def llm_service():
    service = LLMService()
    # Mock _sleep 以加速测试
    service._sleep = AsyncMock()
    return service


@pytest.fixture
def sample_query():
    return LLMQueryDTO(
        session_id=uuid.uuid4(),
        query_text="请帮我解释一下机器学习的原理",
    )


# ============================================================
# stream_response Tests
# ============================================================


class TestStreamResponse:
    """流式输出测试"""

    @pytest.mark.asyncio
    async def test_stream_response_yields_chars(self, llm_service, sample_query):
        """流式输出应逐字符 yield"""
        chunks = []
        async for chunk in llm_service.stream_response(sample_query):
            chunks.append(chunk)

        # 每个 chunk 应该是单个字符
        assert all(len(c) == 1 for c in chunks)
        # 合并后应该是完整的 mock 响应
        full_response = "".join(chunks)
        assert len(full_response) > 0
        assert sample_query.query_text[:30] in full_response

    @pytest.mark.asyncio
    async def test_stream_response_calls_sleep(self, llm_service, sample_query):
        """流式输出应调用 _sleep 模拟延迟"""
        async for _ in llm_service.stream_response(sample_query):
            pass

        # _sleep 应该被调用了多次
        assert llm_service._sleep.call_count > 0


# ============================================================
# generate_response Tests
# ============================================================


class TestGenerateResponse:
    """非流式输出测试"""

    @pytest.mark.asyncio
    async def test_generate_response_returns_dto(self, llm_service, sample_query):
        """非流式输出应返回 LLMResultDTO"""
        result = await llm_service.generate_response(sample_query)

        assert isinstance(result, LLMResultDTO)
        assert result.success is True
        assert len(result.content) > 0
        assert result.latency_ms is not None
        assert result.latency_ms >= 0
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_generate_response_content_contains_query(
        self, llm_service, sample_query
    ):
        """响应中应包含用户查询内容的引用"""
        result = await llm_service.generate_response(sample_query)

        assert sample_query.query_text[:30] in result.content

    @pytest.mark.asyncio
    async def test_generate_response_with_empty_query(self, llm_service):
        """空查询也应正常返回"""
        query = LLMQueryDTO(
            session_id=uuid.uuid4(),
            query_text="",
        )
        result = await llm_service.generate_response(query)

        assert isinstance(result, LLMResultDTO)
        assert result.success is True


# ============================================================
# Mock Response Tests
# ============================================================


class TestMockResponse:
    """Mock 响应生成测试"""

    def test_generate_mock_response(self, llm_service):
        """Mock 响应应包含预设的占位文本"""
        response = llm_service._generate_mock_response("测试问题")

        assert "模拟" in response
        assert "测试问题" in response

    def test_generate_mock_response_truncates_long_query(self, llm_service):
        """长查询在 Mock 响应中应被截断"""
        long_query = "A" * 100
        response = llm_service._generate_mock_response(long_query)

        # 查询内容应被截断到 30 字符
        assert "A" * 30 in response
        assert "A" * 31 not in response
