"""
Prompt 模板管理 (Jinja2)

使用 Jinja2 模板引擎管理 System Prompt，支持：
- 变量渲染（如用户名、知识库内容注入）
- 条件逻辑（如有无 RAG 上下文时使用不同指令）
- 模板继承与复用
"""

from typing import Any

from jinja2 import BaseLoader, Environment
from jinja2.environment import Template

from backend.ai.core.prompt_resolver import get_prompt_resolver

# ============================================================
# Jinja2 环境（全局单例，字符串模板模式）
# ============================================================

_env = Environment(
    loader=BaseLoader(),
    autoescape=False,  # Prompt 不需要 HTML 转义
    keep_trailing_newline=True,
)


# ============================================================
# 编译后的模板对象（启动时一次性编译）
# ============================================================

_prompt_resolver = get_prompt_resolver()

DEFAULT_SYSTEM_TEMPLATE = _prompt_resolver.get_template("default_system")
RAG_SYSTEM_TEMPLATE = _prompt_resolver.get_template("rag_system")
SUMMARIZE_TEMPLATE = _prompt_resolver.get_template("summarize")

# ============================================================
# 默认变量
# ============================================================

DEFAULT_TEMPLATE_VARS = _prompt_resolver.get_default_variables()


def render_system_prompt(
    template: Template | None = None,
    **kwargs: Any,
) -> str:
    """
    渲染 System Prompt

    Args:
        template: Jinja2 Template 对象，默认使用 DEFAULT_SYSTEM_TEMPLATE
        **kwargs: 模板变量，会与 DEFAULT_TEMPLATE_VARS 合并

    Returns:
        渲染后的 Prompt 字符串

    Examples:
        # 使用默认模板
        prompt = render_system_prompt()

        # 自定义变量
        prompt = render_system_prompt(user_name="Alice")

        # 使用 RAG 模板
        prompt = render_system_prompt(
            template=RAG_SYSTEM_TEMPLATE,
            context_chunks=["文档片段1", "文档片段2"],
        )
    """
    tpl = template or _prompt_resolver.get_template("default_system")
    variables = {**_prompt_resolver.get_default_variables(), **kwargs}
    return tpl.render(**variables)
