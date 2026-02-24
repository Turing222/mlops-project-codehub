"""
PromptManager 单元测试 (Jinja2 版)

覆盖：
- Jinja2 模板渲染（变量注入、条件逻辑）
- 无历史消息时组装 [System + User]
- 有历史消息时组装 [System + History + User]
- Token 超限时截断最早的历史轮次
- 空 System Prompt 时不插入 system 消息
- _group_into_rounds 分组逻辑
"""

import pytest

from backend.services.llm_core.manager import AssembledPrompt, PromptManager
from backend.services.llm_core.templates import (
    DEFAULT_SYSTEM_TEMPLATE,
    RAG_SYSTEM_TEMPLATE,
    render_system_prompt,
)
from backend.services.llm_core.tokens import count_messages_tokens, count_tokens


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def manager():
    """标准 PromptManager，使用较宽松的 Token 限制"""
    return PromptManager(
        system_template=DEFAULT_SYSTEM_TEMPLATE,
        template_vars={"app_name": "TestBot"},
        max_context_tokens=4096,
        max_history_rounds=10,
        reserved_response_tokens=512,
    )


@pytest.fixture
def tight_manager():
    """Token 预算很紧的 PromptManager，用于测试截断"""
    return PromptManager(
        system_template=DEFAULT_SYSTEM_TEMPLATE,
        template_vars={"app_name": "TestBot"},
        max_context_tokens=200,
        max_history_rounds=10,
        reserved_response_tokens=50,
    )


@pytest.fixture
def sample_history():
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

    def test_default_template_renders(self):
        """默认模板可以正常渲染"""
        result = render_system_prompt()
        assert "Obsidian Mentor AI" in result
        assert len(result) > 0

    def test_template_with_custom_app_name(self):
        """自定义 app_name 变量"""
        result = render_system_prompt(app_name="MyBot")
        assert "MyBot" in result
        assert "Obsidian Mentor AI" not in result

    def test_template_with_user_name(self):
        """注入 user_name 时包含用户信息"""
        result = render_system_prompt(user_name="Alice")
        assert "Alice" in result

    def test_template_without_user_name(self):
        """不提供 user_name 时不包含用户信息行"""
        result = render_system_prompt(user_name="")
        assert "当前用户" not in result

    def test_rag_template_renders_chunks(self):
        """RAG 模板正确渲染文档片段"""
        chunks = ["文档A的内容", "文档B的内容"]
        result = render_system_prompt(
            template=RAG_SYSTEM_TEMPLATE,
            context_chunks=chunks,
        )
        assert "文档A的内容" in result
        assert "文档B的内容" in result
        assert "[1]" in result
        assert "[2]" in result


# ============================================================
# 基础组装测试
# ============================================================


class TestBasicAssembly:
    """基础 Prompt 组装"""

    def test_assemble_no_history(self, manager):
        """无历史消息时：[System + User]"""
        result = manager.assemble([], "你好")

        assert isinstance(result, AssembledPrompt)
        assert len(result.messages) == 2  # system + user
        assert result.messages[0]["role"] == "system"
        assert "TestBot" in result.messages[0]["content"]  # Jinja2 渲染的变量
        assert result.messages[-1]["role"] == "user"
        assert result.messages[-1]["content"] == "你好"
        assert result.history_rounds_used == 0
        assert result.truncated is False
        assert result.total_tokens > 0

    def test_assemble_with_history(self, manager, sample_history):
        """有历史消息时：[System + History + User]"""
        result = manager.assemble(sample_history, "帮我写个代码")

        assert result.messages[0]["role"] == "system"
        assert result.messages[-1]["role"] == "user"
        assert result.messages[-1]["content"] == "帮我写个代码"
        assert result.history_rounds_used == 2  # 两轮历史
        assert result.truncated is False

    def test_assemble_with_extra_vars(self, manager):
        """assemble 时通过 extra_vars 注入额外变量"""
        result = manager.assemble([], "你好", extra_vars={"user_name": "Bob"})

        system_content = result.messages[0]["content"]
        assert "Bob" in system_content

    def test_assemble_preserves_message_order(self, manager, sample_history):
        """组装后消息顺序正确"""
        result = manager.assemble(sample_history, "新问题")

        roles = [m["role"] for m in result.messages]
        # system -> user -> assistant -> user -> assistant -> user(current)
        assert roles[0] == "system"
        assert roles[-1] == "user"
        assert result.messages[-1]["content"] == "新问题"


# ============================================================
# 截断测试
# ============================================================


class TestTruncation:
    """Token 超限截断"""

    def test_truncation_drops_oldest_rounds(self, tight_manager):
        """Token 超限时应该丢弃最早的历史轮次"""
        long_history = [
            {"role": "user", "content": "第一个很长的问题" * 10},
            {"role": "assistant", "content": "第一个很长的回答" * 10},
            {"role": "user", "content": "短问题"},
            {"role": "assistant", "content": "短回答"},
        ]
        result = tight_manager.assemble(long_history, "新问题")

        assert result.truncated is True
        assert result.history_rounds_used < 2

    def test_max_history_rounds_honored(self):
        """最大历史轮数限制"""
        manager = PromptManager(
            system_template=DEFAULT_SYSTEM_TEMPLATE,
            template_vars={"app_name": "TestBot"},
            max_context_tokens=100000,
            max_history_rounds=2,
            reserved_response_tokens=512,
        )
        history = []
        for i in range(5):
            history.append({"role": "user", "content": f"问题{i}"})
            history.append({"role": "assistant", "content": f"回答{i}"})

        result = manager.assemble(history, "新问题")
        assert result.history_rounds_used <= 2


# ============================================================
# 分组逻辑测试
# ============================================================


class TestGroupIntoRounds:
    """_group_into_rounds 方法"""

    def test_empty_history(self):
        rounds = PromptManager._group_into_rounds([])
        assert rounds == []

    def test_standard_rounds(self):
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

    def test_skips_system_messages(self):
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
    """Token 计算工具"""

    def test_count_tokens_empty(self):
        assert count_tokens("") == 0

    def test_count_tokens_nonempty(self):
        result = count_tokens("Hello, world!")
        assert result > 0

    def test_count_messages_tokens_empty(self):
        assert count_messages_tokens([]) == 0

    def test_count_messages_tokens_basic(self):
        messages = [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ]
        result = count_messages_tokens(messages)
        assert result > 0
