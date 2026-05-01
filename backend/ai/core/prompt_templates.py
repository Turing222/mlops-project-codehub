"""Prompt template compatibility exports.

职责：提供历史调用方使用的模板常量和 render_system_prompt。
边界：模板加载和 fallback 策略由 PromptResolver 负责。
副作用：模块导入时会解析默认模板，用于尽早暴露配置错误。
"""

from typing import Any

from jinja2 import BaseLoader, Environment
from jinja2.environment import Template

from backend.ai.core.prompt_resolver import get_prompt_resolver

_env = Environment(
    loader=BaseLoader(),
    autoescape=False,  # Prompt 不需要 HTML 转义
    keep_trailing_newline=True,
)

_prompt_resolver = get_prompt_resolver()

DEFAULT_SYSTEM_TEMPLATE = _prompt_resolver.get_template("default_system")
RAG_SYSTEM_TEMPLATE = _prompt_resolver.get_template("rag_system")
SUMMARIZE_TEMPLATE = _prompt_resolver.get_template("summarize")

DEFAULT_TEMPLATE_VARS = _prompt_resolver.get_default_variables()


def render_system_prompt(
    template: Template | None = None,
    **kwargs: Any,
) -> str:
    """用默认变量和调用方变量渲染 system prompt。"""
    tpl = template or _prompt_resolver.get_template("default_system")
    variables = {**_prompt_resolver.get_default_variables(), **kwargs}
    return tpl.render(**variables)
