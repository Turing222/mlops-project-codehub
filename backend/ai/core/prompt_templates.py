"""
Prompt 模板管理 (Jinja2)

使用 Jinja2 模板引擎管理 System Prompt，支持：
- 变量渲染（如用户名、知识库内容注入）
- 条件逻辑（如有无 RAG 上下文时使用不同指令）
- 模板继承与复用
"""

from jinja2 import BaseLoader, Environment

# ============================================================
# Jinja2 环境（全局单例，字符串模板模式）
# ============================================================

_env = Environment(
    loader=BaseLoader(),
    autoescape=False,       # Prompt 不需要 HTML 转义
    keep_trailing_newline=True,
)

# ============================================================
# 模板字符串定义
# ============================================================

# 默认系统提示词
_DEFAULT_SYSTEM_TEMPLATE = """\
你是 {{ app_name }}，一个专业的 MLOps 平台智能助手。
你擅长回答关于模型训练、部署、分布式追踪和数据管理的问题。
请用专业但易懂的中文回答用户的问题。
如果你不确定答案，请诚实地说明，不要编造信息。
{% if user_name %}当前用户: {{ user_name }}。{% endif %}\
"""

# RAG 检索增强模板
_RAG_SYSTEM_TEMPLATE = """\
你是 {{ app_name }}，一个基于知识库的智能助手。
请根据以下参考资料回答用户的问题。
如果参考资料中没有相关信息，请基于你的通用知识回答，并注明这不是来自知识库的内容。

--- 参考资料 ---
{% for chunk in context_chunks %}
[{{ loop.index }}] {{ chunk }}
{% endfor %}
--- 参考资料结束 ---\
"""

# 对话总结模板（预留，未来上下文压缩功能使用）
_SUMMARIZE_TEMPLATE = """\
请将以下对话历史浓缩为一段简洁的摘要，保留关键信息和上下文。
摘要应作为后续对话的背景信息使用。

对话历史:
{% for msg in messages %}
{{ msg.role }}: {{ msg.content }}
{% endfor %}\
"""

# ============================================================
# 编译后的模板对象（启动时一次性编译）
# ============================================================

DEFAULT_SYSTEM_TEMPLATE = _env.from_string(_DEFAULT_SYSTEM_TEMPLATE)
RAG_SYSTEM_TEMPLATE = _env.from_string(_RAG_SYSTEM_TEMPLATE)
SUMMARIZE_TEMPLATE = _env.from_string(_SUMMARIZE_TEMPLATE)

# ============================================================
# 默认变量
# ============================================================

DEFAULT_TEMPLATE_VARS = {
    "app_name": "Obsidian Mentor AI",
    "user_name": "",
}


def render_system_prompt(
    template=None,
    **kwargs,
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
    tpl = template or DEFAULT_SYSTEM_TEMPLATE
    variables = {**DEFAULT_TEMPLATE_VARS, **kwargs}
    return tpl.render(**variables)
