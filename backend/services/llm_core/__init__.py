"""
LLM Core — 对话能力核心模块

对外暴露:
- PromptManager: Prompt 动态组装与截断
- AssembledPrompt: 组装结果数据类
- render_system_prompt: Jinja2 模板渲染工具
- count_tokens / count_messages_tokens: Token 计算工具
- 模板对象
"""

from backend.services.llm_core.manager import AssembledPrompt, PromptManager
from backend.services.llm_core.templates import (
    DEFAULT_SYSTEM_TEMPLATE,
    RAG_SYSTEM_TEMPLATE,
    SUMMARIZE_TEMPLATE,
    render_system_prompt,
)
from backend.services.llm_core.tokens import count_messages_tokens, count_tokens

__all__ = [
    "PromptManager",
    "AssembledPrompt",
    "render_system_prompt",
    "count_tokens",
    "count_messages_tokens",
    "DEFAULT_SYSTEM_TEMPLATE",
    "RAG_SYSTEM_TEMPLATE",
    "SUMMARIZE_TEMPLATE",
]
