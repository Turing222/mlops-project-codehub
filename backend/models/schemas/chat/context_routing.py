"""Context routing schemas.

职责：定义上下文路由的通用 mode/source 类型，供 API、Worker payload 和 planner 共享。
边界：只描述路由意图，不绑定具体 provider 或执行逻辑。
"""

from typing import Literal

ContextMode = Literal["auto", "kb_only", "web_only", "off"]
ContextSource = Literal["kb", "web", "skill", "mcp"]
RAGRetrievalMode = Literal["vector", "fulltext", "hybrid"]


def resolve_context_mode(
    *,
    context_mode: ContextMode | None,
    enable_external_context: bool,
) -> ContextMode:
    """Resolve legacy external-context flag into the v1 routing mode."""
    if context_mode is not None:
        return context_mode
    return "auto" if enable_external_context else "kb_only"


def is_external_context_allowed(
    *,
    context_mode: ContextMode | None,
    enable_external_context: bool,
    external_context_enabled: bool,
) -> bool:
    """Determine whether external context retrieval is allowed.

    Centralises the logic previously duplicated between
    WorkerRAGOrchestrator._external_context_allowed and RAGPlanningService.plan.
    """
    mode = resolve_context_mode(
        context_mode=context_mode,
        enable_external_context=enable_external_context,
    )
    return (
        mode in {"auto", "web_only"}
        and (context_mode is not None or enable_external_context)
        and external_context_enabled
    )


def source_selected(sources: list[ContextSource], source: ContextSource | str) -> bool:
    """Return true when a source appears in the route plan."""
    return source in sources
