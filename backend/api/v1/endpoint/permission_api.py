from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_current_active_user
from backend.config.permissions import get_permission_policy, get_permissions_config
from backend.models.orm.access import WorkspaceRole
from backend.models.orm.user import User
from backend.models.schemas.permission_schema import (
    PermissionDescription,
    PermissionPolicyResponse,
)
from backend.services.permission_types import Permission

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]


@router.get("/policy", response_model=PermissionPolicyResponse)
async def get_permission_policy_metadata(
    _: CurrentUser,
) -> PermissionPolicyResponse:
    config = get_permissions_config()
    policy = get_permission_policy()

    permissions = [
        PermissionDescription(
            value=Permission(permission),
            description=definition.description,
        )
        for permission, definition in config.permissions.items()
    ]
    role_permissions = {
        role.value: sorted(
            policy.role_permissions.get(role, frozenset()), key=lambda item: item.value
        )
        for role in WorkspaceRole
    }

    return PermissionPolicyResponse(
        permissions=permissions,
        roles=list(WorkspaceRole),
        role_permissions=role_permissions,
    )
