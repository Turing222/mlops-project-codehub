"""
LLM Core — 对话能力核心模块

对外暴露:
- PromptManager: Prompt 组装与渲染
- ChatContextBuilder: 上下文编排
- ContextBudgeter: Token 预算管理
- LiveWindowBuilder: 历史窗口构建
- MessageCompressor: 消息压缩
- AssembledPrompt: 组装结果数据类
- render_system_prompt: Jinja2 模板渲染工具
- estimate_tokens / estimate_messages_tokens: Token 估算工具
- count_tokens / count_messages_tokens: 兼容旧导入的估算别名
- 模板对象
"""

from backend.ai.core.chat_context_builder import ChatContextBuilder, PreparedChatContext
from backend.ai.core.context_budgeter import BudgetBlock, ContextBudgeter
from backend.ai.core.live_window_builder import LiveWindowBuilder, LiveWindowResult
from backend.ai.core.message_compressor import MessageCompressor
from backend.ai.core.prompt_manager import AssembledPrompt, PromptManager
from backend.ai.core.prompt_templates import (
    DEFAULT_SYSTEM_TEMPLATE,
    RAG_SYSTEM_TEMPLATE,
    SUMMARIZE_TEMPLATE,
    render_system_prompt,
)
from backend.ai.core.token_counter import (
    count_messages_tokens,
    count_tokens,
    estimate_messages_tokens,
    estimate_tokens,
)

__all__ = [
    "DEFAULT_SYSTEM_TEMPLATE",
    "RAG_SYSTEM_TEMPLATE",
    "SUMMARIZE_TEMPLATE",
    "AssembledPrompt",
    "BudgetBlock",
    "ChatContextBuilder",
    "ContextBudgeter",
    "LiveWindowBuilder",
    "LiveWindowResult",
    "MessageCompressor",
    "PreparedChatContext",
    "PromptManager",
    "count_messages_tokens",
    "count_tokens",
    "estimate_messages_tokens",
    "estimate_tokens",
    "render_system_prompt",
]
