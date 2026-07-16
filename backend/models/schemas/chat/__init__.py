"""Chat schema package — re-exports for backward compatibility.

职责：聚合 chat 子模块的公开类型，保持旧 import 路径可用。
边界：本模块不定义任何新类型，只做 re-export。
"""

from backend.models.enums import MessageRole, MessageStatus
from backend.models.schemas.chat.api import (
    ChatQueryResponse,
    MessageResponse,
    QuerySentRequest,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
    SessionUpdateRequest,
)
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.models.schemas.chat.context_state import ContextState
from backend.models.schemas.chat.dto import (
    ConversationMessage,
    LLMQueryDTO,
    LLMResultDTO,
)
from backend.models.schemas.chat.params import LLMExtraBody, LLMThinkingConfig
from backend.models.schemas.chat.payloads import (
    GenerationAttemptPayload,
    GenerationPayload,
    GenerationResult,
    LLMTaskPayload,
)

# Backward-compatible aliases
ChatMessageRole = MessageRole
MessageStatusEnum = MessageStatus

__all__ = [
    "ChatMessageRole",
    "ChatQueryCommand",
    "ChatQueryResponse",
    "ContextState",
    "ConversationMessage",
    "GenerationAttemptPayload",
    "GenerationPayload",
    "GenerationResult",
    "LLMExtraBody",
    "LLMQueryDTO",
    "LLMResultDTO",
    "LLMTaskPayload",
    "LLMThinkingConfig",
    "MessageResponse",
    "MessageRole",
    "MessageStatus",
    "MessageStatusEnum",
    "QuerySentRequest",
    "SessionDetailResponse",
    "SessionListResponse",
    "SessionResponse",
    "SessionUpdateRequest",
]
