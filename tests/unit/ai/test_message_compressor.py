"""Message compressor unit tests.

职责：验证消息截断、压缩和批量预算控制；边界：使用 fake summarizer，不调用真实 LLM；副作用：无。
"""

from unittest.mock import AsyncMock

from backend.ai.core.message_compressor import MessageCompressor
from backend.ai.core.token_counter import count_messages_tokens


class TestTruncate:
    def test_short_content_noop(self) -> None:
        content = "短文本"
        result = MessageCompressor.truncate(content, 100)
        assert result == content

    def test_long_content_truncates_at_boundary(self) -> None:
        content = "第一句话。第二句话。第三句话。第四句话。"
        result = MessageCompressor.truncate(content, 7)
        assert len(result) <= 7
        assert result == "第一句话。"

    def test_falls_back_to_hard_truncate_when_no_boundary(self) -> None:
        content = "ABC" + "defghijklmnop" * 10
        result = MessageCompressor.truncate(content, 20)
        assert len(result) == 20
        assert result == content[:20]

    def test_empty_target_returns_empty(self) -> None:
        result = MessageCompressor.truncate("一些内容", 0)
        assert result == ""

    def test_boundary_uses_last_boundary_in_range(self) -> None:
        content = "A" * 80 + "。B" * 20
        result = MessageCompressor.truncate(content, 90)
        assert len(result) <= 90
        assert result.endswith("。")


class TestTruncateHeadTail:
    def test_short_content_noop(self) -> None:
        content = "短文本"
        result = MessageCompressor.truncate_head_tail(content, 5, 5)
        assert result == content

    def test_preserves_head_and_tail(self) -> None:
        content = "AAAAABBBBBCCCCCDDDDDEEEEE"
        result = MessageCompressor.truncate_head_tail(content, 5, 5)
        assert result == "AAAAA\n...\nEEEEE"

    def test_zero_tail(self) -> None:
        content = "A" * 100
        result = MessageCompressor.truncate_head_tail(content, 10, 0)
        assert result == "AAAAAAAAAA\n..."

    def test_zero_head(self) -> None:
        content = "A" * 100
        result = MessageCompressor.truncate_head_tail(content, 0, 10)
        assert result == "...\nAAAAAAAAAA"


class TestCompress:
    def test_short_content_noop(self) -> None:
        compressor = MessageCompressor()
        result = compressor.compress("短文本", 100)
        assert result == "短文本"

    def test_long_content_truncates(self) -> None:
        compressor = MessageCompressor()
        content = "A" * 200
        result = compressor.compress(content, 50)
        assert len(result) <= 50

    def test_compress_below_threshold_noop(self) -> None:
        compressor = MessageCompressor(truncation_threshold_chars=1000)
        content = "A" * 500
        result = compressor.compress(content, 400)
        assert len(result) <= 400


class TestCompressAsync:
    async def test_short_content_noop(self) -> None:
        compressor = MessageCompressor()
        result = await compressor.compress_async("短文本", 100)
        assert result == "短文本"

    async def test_without_summarizer_falls_back_to_truncate(self) -> None:
        compressor = MessageCompressor()
        content = "A" * 200
        result = await compressor.compress_async(content, 50)
        assert len(result) <= 50

    async def test_with_summarizer_calls_llm(self) -> None:
        mock_summarize = AsyncMock(return_value="LLM 摘要结果")
        compressor = MessageCompressor(summarizer=mock_summarize)
        content = "A" * 200
        result = await compressor.compress_async(content, 30)
        assert result == "LLM 摘要结果"
        mock_summarize.assert_awaited_once_with(content, 30)

    async def test_summarizer_failure_falls_back_to_truncate(self) -> None:
        mock_summarize = AsyncMock(side_effect=RuntimeError("LLM 挂了"))
        compressor = MessageCompressor(summarizer=mock_summarize)
        content = "A" * 200
        result = await compressor.compress_async(content, 50)
        assert len(result) <= 50
        assert result == content[:50]


class TestCompressBatch:
    async def test_empty_messages(self) -> None:
        compressor = MessageCompressor()
        result = await compressor.compress_batch([], 100, "gpt-4")
        assert result == []

    async def test_fits_budget_no_compression(self) -> None:
        compressor = MessageCompressor()
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        budget = count_messages_tokens(messages, "gpt-4") + 100
        result = await compressor.compress_batch(messages, budget, "gpt-4")
        assert result == messages

    async def test_drops_oldest_when_over_budget(self) -> None:
        compressor = MessageCompressor()
        old_msg = {"role": "user", "content": "旧消息" * 100}
        recent_msg = {"role": "assistant", "content": "新消息"}
        messages = [old_msg, recent_msg]
        budget = count_messages_tokens([recent_msg], "gpt-4") + 10
        result = await compressor.compress_batch(messages, budget, "gpt-4")
        assert len(result) == 1
        assert result[0] == recent_msg

    async def test_compresses_when_single_message_too_large(self) -> None:
        compressor = MessageCompressor()
        huge_msg = {"role": "user", "content": "A" * 10000}
        tiny_budget = 20
        result = await compressor.compress_batch([huge_msg], tiny_budget, "gpt-4")
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert len(result[0]["content"]) <= 60

    async def test_keeps_recent_messages_when_over_budget(self) -> None:
        compressor = MessageCompressor()
        messages = [
            {"role": "user", "content": "第一轮用户" * 50},
            {"role": "assistant", "content": "第一轮助手" * 50},
            {"role": "user", "content": "第二轮用户" * 50},
            {"role": "assistant", "content": "第二轮助手" * 50},
            {"role": "user", "content": "最新问题"},
        ]
        budget = count_messages_tokens(messages[-2:], "gpt-4") + 10
        result = await compressor.compress_batch(messages, budget, "gpt-4")
        assert len(result) >= 2
        # 最新消息一定保留
        assert result[-1]["content"] == "最新问题"
