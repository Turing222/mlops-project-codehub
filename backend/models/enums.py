"""Domain enums shared across layers.

职责：定义跨层共享的领域枚举，消除 schema→ORM / config→service 倒依赖。
边界：本模块不依赖 ORM 模型、service、config 任何层。
"""

from enum import StrEnum


class MessageStatus(StrEnum):
    THINKING = "thinking"
    STREAMING = "streaming"
    SUCCESS = "success"
    FAILED = "failed"


class ChatGenerationStatus(StrEnum):
    """Durable lifecycle states for one logical Chat generation request."""

    PREPARED = "prepared"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


class Permission(StrEnum):
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_MANAGE = "workspace:manage"
    ROLE_MANAGE = "role:manage"
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    FILE_DELETE = "file:delete"
    CHAT_READ = "chat:read"
    CHAT_WRITE = "chat:write"
    AUDIT_READ = "audit:read"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
