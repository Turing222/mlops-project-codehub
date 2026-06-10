"""Prompt manager unit tests.

职责：验证模板渲染、消息组装、历史分组和 token 计数；边界：使用本地模板和纯内存消息，不访问外部 prompt 服务；副作用：无。
"""

import pytest

from backend.ai.core.prompt_manager import AssembledPrompt, PromptManager
from backend.ai.core.prompt_templates import (
    DEFAULT_SYSTEM_TEMPLATE,
    RAG_SYSTEM_TEMPLATE,
    render_system_prompt,
)
from backend.ai.core.token_counter import (
    count_messages_tokens,
    count_tokens,
    estimate_messages_tokens,
    estimate_tokens,
)


@pytest.fixture
def manager() -> PromptManager:
    """标准 PromptManager"""
    return PromptManager(
        system_template=DEFAULT_SYSTEM_TEMPLATE,
        template_vars={"app_name": "TestBot"},
        max_context_tokens=4096,
        max_history_rounds=10,
        reserved_response_tokens=512,
    )


@pytest.fixture
def sample_history() -> list[dict[str, str]]:
    """两轮对话历史"""
    return [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮你的吗？"},
        {"role": "user", "content": "今天天气怎么样？"},
        {"role": "assistant", "content": "今天天气晴朗，非常适合外出。"},
    ]


# ============================================================
# Jinja2 模板渲染测试
# ============================================================


class TestTemplateRendering:
    """Jinja2 模板渲染"""

    def test_default_template_renders(self) -> None:
        result = render_system_prompt()
        assert "Dewflow" in result
        assert len(result) > 0

    def test_template_with_custom_app_name(self) -> None:
        result = render_system_prompt(app_name="MyBot")
        assert "MyBot" in result
        assert "Dewflow" not in result

    def test_template_with_user_name(self) -> None:
        result = render_system_prompt(user_name="Alice")
        assert "Alice" in result

    def test_template_without_user_name(self) -> None:
        result = render_system_prompt(user_name="")
        assert "当前用户" not in result

    def test_rag_template_renders_chunks(self) -> None:
        chunks = ["[R1.1] 文档A的内容", "[R2.1] 文档B的内容"]
        result = render_system_prompt(
            template=RAG_SYSTEM_TEMPLATE,
            context_chunks=chunks,
        )
        assert "文档A的内容" in result
        assert "文档B的内容" in result
        assert "[R1.1]" in result
        assert "[R2.1]" in result

    def test_rag_template_requires_knowledge_evidence(self) -> None:
        result = render_system_prompt(
            template=RAG_SYSTEM_TEMPLATE,
            context_chunks=[],
        )
        assert "只能根据参考资料回答" in result
        assert "无法基于已提供资料回答" in result
        assert "基于你的通用知识回答" not in result


# ============================================================
# 基础组装测试
# ============================================================


class TestBasicAssembly:
    """基础 Prompt 组装"""

    def test_assemble_no_history(self, manager) -> None:
        result = manager.assemble([], "你好")
        assert isinstance(result, AssembledPrompt)
        assert len(result.messages) == 2  # system + user
        assert result.messages[0]["role"] == "system"
        assert "TestBot" in result.messages[0]["content"]
        assert result.messages[-1]["role"] == "user"
        assert result.messages[-1]["content"] == "你好"
        assert result.history_rounds_used == 0
        assert result.truncated is False
        assert result.total_tokens > 0

    def test_assemble_with_history(self, manager, sample_history) -> None:
        result = manager.assemble(sample_history, "帮我写个代码")
        assert result.messages[0]["role"] == "system"
        assert result.messages[-1]["role"] == "user"
        assert result.messages[-1]["content"] == "帮我写个代码"
        assert result.history_rounds_used == 2  # 两轮历史
        assert result.truncated is False

    def test_assemble_with_extra_vars(self, manager) -> None:
        result = manager.assemble([], "你好", extra_vars={"user_name": "Bob"})
        system_content = result.messages[0]["content"]
        assert "Bob" in system_content

    def test_assemble_preserves_message_order(self, manager, sample_history) -> None:
        result = manager.assemble(sample_history, "新问题")
        roles = [m["role"] for m in result.messages]
        assert roles[0] == "system"
        assert roles[-1] == "user"
        assert result.messages[-1]["content"] == "新问题"


# ============================================================
# 分组逻辑测试
# ============================================================


class TestGroupIntoRounds:
    """_group_into_rounds 方法"""

    def test_empty_history(self) -> None:
        rounds = PromptManager._group_into_rounds([])
        assert rounds == []

    def test_standard_rounds(self) -> None:
        history = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
        ]
        rounds = PromptManager._group_into_rounds(history)
        assert len(rounds) == 2
        assert rounds[0] == [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
        ]

    def test_skips_system_messages(self) -> None:
        history = [
            {"role": "system", "content": "旧的系统提示"},
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
        ]
        rounds = PromptManager._group_into_rounds(history)
        assert len(rounds) == 1
        assert all(m["role"] != "system" for m in rounds[0])


# ============================================================
# Token 工具测试
# ============================================================


class TestTokenUtils:
    """Token 估算工具"""

    def test_count_tokens_empty(self) -> None:
        assert count_tokens("") == 0

    def test_estimate_tokens_nonempty(self) -> None:
        result = estimate_tokens("Hello, world!")
        assert result > 0

    def test_estimate_tokens_handles_mixed_cjk_and_latin_text(self) -> None:
        chinese = estimate_tokens("你好世界")
        english = estimate_tokens("hello world")
        mixed = estimate_tokens("你好 hello")

        assert chinese > 0
        assert english > 0
        assert mixed > 0

    def test_estimate_tokens_is_conservative_for_short_words(self) -> None:
        text = "a " * 100

        assert estimate_tokens(text) >= 100

    def test_estimate_tokens_is_conservative_for_code_like_text(self) -> None:
        code = "if (x == y) { foo_bar += baz.qux(); }\n" * 10

        assert estimate_tokens(code) > len(code) // 4

    def test_count_messages_tokens_empty(self) -> None:
        assert count_messages_tokens([]) == 0

    def test_estimate_messages_tokens_includes_message_overhead(self) -> None:
        messages = [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ]
        content_only = estimate_tokens("你是助手") + estimate_tokens("你好")
        result = estimate_messages_tokens(messages)

        assert result > content_only
