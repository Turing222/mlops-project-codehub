"""Permission enum definitions.

职责：集中定义代码中可引用的权限标识。
边界：角色到权限的映射由配置文件和 PermissionPolicy 决定。
"""

from enum import StrEnum


class Permission(StrEnum):
    """工作区权限标识。"""

    WORKSPACE_READ = "workspace:read"
    WORKSPACE_MANAGE = "workspace:manage"
    ROLE_MANAGE = "role:manage"
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    FILE_DELETE = "file:delete"
    CHAT_READ = "chat:read"
    CHAT_WRITE = "chat:write"
    AUDIT_READ = "audit:read"
