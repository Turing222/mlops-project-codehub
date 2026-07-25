"""Provider reasoning filter unit tests.

职责：验证完整、跨 chunk、未闭合和大小写 `<think>` 内容不会离开过滤边界。
边界：纯字符串测试，不启动 Redis、数据库或 provider。
"""

from backend.application.chat.provider_reasoning import (
    StreamingReasoningFilter,
    strip_provider_reasoning,
)


def test_strip_provider_reasoning_keeps_only_answer() -> None:
    content = "prefix<think>synthetic-reasoning-secret</think>final answer"

    assert strip_provider_reasoning(content) == "prefixfinal answer"


def test_streaming_filter_strips_tags_split_across_chunks() -> None:
    reasoning_filter = StreamingReasoningFilter()
    chunks = ["safe<thi", "nk>private", " reasoning</th", "ink>answer"]

    visible = "".join(reasoning_filter.push(chunk) for chunk in chunks)
    visible += reasoning_filter.finish()

    assert visible == "safeanswer"
    assert reasoning_filter.saw_reasoning is True


def test_streaming_filter_drops_unclosed_reasoning() -> None:
    reasoning_filter = StreamingReasoningFilter()

    visible = reasoning_filter.push("answer<think>never expose this")
    visible += reasoning_filter.finish()

    assert visible == "answer"


def test_strip_provider_reasoning_removes_stray_close_tag() -> None:
    assert strip_provider_reasoning("answer</THINK>tail") == "answertail"
