"""
Compatibility aggregation module for FastAPI dependencies.

Use this module when importing dependencies from API endpoints to avoid
touching call sites while deps are split into focused modules.
"""

from backend.api.deps.ai import (
    get_chunking_service,
    get_llm_service,
    get_rag_embedder,
    get_rag_service,
    get_vector_index_service,
)
from backend.api.deps.auth import (
    get_current_active_user,
    get_current_superuser,
    get_current_user,
    get_login_data,
    reusable_oauth2,
)
from backend.api.deps.services import (
    get_knowledge_service,
    get_knowledge_upload_service,
    get_session_query_service,
    get_task_service,
    get_user_import_service,
    get_user_service,
)
from backend.api.deps.uow import get_uow
from backend.api.deps.workflows import (
    get_chat_nonstream_workflow,
    get_chat_workflow,
    get_knowledge_rag_workflow,
)

__all__ = [
    "reusable_oauth2",
    "get_uow",
    "get_current_user",
    "get_current_active_user",
    "get_current_superuser",
    "get_login_data",
    "get_llm_service",
    "get_rag_embedder",
    "get_rag_service",
    "get_chunking_service",
    "get_vector_index_service",
    "get_chat_nonstream_workflow",
    "get_chat_workflow",
    "get_knowledge_service",
    "get_knowledge_upload_service",
    "get_knowledge_rag_workflow",
    "get_task_service",
    "get_session_query_service",
    "get_user_service",
    "get_user_import_service",
]
