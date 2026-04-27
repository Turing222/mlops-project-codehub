from enum import StrEnum


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
