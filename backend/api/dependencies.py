"""
Compatibility aggregation module for FastAPI dependencies.

Use this module when importing dependencies from API endpoints to avoid
touching call sites while deps are split into focused modules.
"""

from importlib import import_module

from backend.api.deps.audit import get_audit_service
from backend.api.deps.auth import (
    get_current_active_user,
    get_current_superuser,
    get_current_user,
    get_login_data,
    reusable_oauth2,
)
from backend.api.deps.permissions import get_permission_service
from backend.api.deps.services import (
    get_credit_service,
    get_feature_flag_service,
    get_knowledge_service,
    get_object_storage,
    get_repo_analysis_service,
    get_session_query_service,
    get_task_service,
    get_user_import_service,
    get_user_service,
    get_workspace_service,
)
from backend.api.deps.uow import get_uow
from backend.api.deps.workflows import (
    get_chat_nonstream_workflow,
    get_chat_workflow,
    get_knowledge_upload_workflow,
    get_repo_analysis_submit_workflow,
)

_AI_EXPORTS = {
    "get_chunking_service",
    "get_llm_service",
    "get_rag_embedder",
    "get_rag_service",
    "get_vector_index_service",
    "get_knowledge_rag_workflow",
}

__all__ = [
    "get_audit_service",
    "get_chat_nonstream_workflow",
    "get_chat_workflow",
    "get_credit_service",
    "get_current_active_user",
    "get_current_superuser",
    "get_current_user",
    "get_feature_flag_service",
    "get_knowledge_service",
    "get_knowledge_upload_workflow",
    "get_login_data",
    "get_object_storage",
    "get_permission_service",
    "get_repo_analysis_service",
    "get_repo_analysis_submit_workflow",
    "get_session_query_service",
    "get_task_service",
    "get_uow",
    "get_user_import_service",
    "get_user_service",
    "get_workspace_service",
    "reusable_oauth2",
]


# 向后兼容的延迟导入：避免 Web 侧直接 import backend.api.deps.ai。
# 新代码应直接从 backend.api.deps.ai 导入 AI 相关依赖。
def __getattr__(name: str):
    if name in _AI_EXPORTS:
        return getattr(import_module("backend.api.deps.ai"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
