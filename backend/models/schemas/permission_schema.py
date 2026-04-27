from pydantic import BaseModel

from backend.models.orm.access import WorkspaceRole
from backend.services.permission_types import Permission


class PermissionDescription(BaseModel):
    value: Permission
    description: str = ""


class RolePolicyResponse(BaseModel):
    value: WorkspaceRole
    permissions: list[Permission]


class PermissionPolicyResponse(BaseModel):
    permissions: list[PermissionDescription]
    roles: list[WorkspaceRole]
    role_permissions: dict[str, list[Permission]]
