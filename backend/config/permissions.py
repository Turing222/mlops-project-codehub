from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from backend.config.loader import ConfigurationError, load_yaml_config
from backend.config.schemas import PermissionsConfig
from backend.models.orm.access import WorkspaceRole
from backend.services.permission_types import Permission


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    role_permissions: dict[WorkspaceRole, frozenset[Permission]]
    superuser_bypass: bool = True
    missing_workspace: str = "deny"
    missing_role: str = "deny"

    def role_has_permission(
        self,
        *,
        role: WorkspaceRole | None,
        permission: Permission,
    ) -> bool:
        if role is None:
            return self.missing_role == "allow"
        return permission in self.role_permissions.get(role, frozenset())

    def allows_missing_workspace(self) -> bool:
        return self.missing_workspace == "allow"


def load_permission_policy(
    *,
    config_dir: str | Path | None = None,
) -> PermissionPolicy:
    config = load_permissions_config(config_dir=config_dir)

    all_permissions = frozenset(Permission)
    role_permissions: dict[WorkspaceRole, frozenset[Permission]] = {}
    for role_name, role_config in config.roles.items():
        role = WorkspaceRole(role_name)
        if role_config.permissions == ["*"]:
            role_permissions[role] = all_permissions
            continue
        role_permissions[role] = frozenset(
            Permission(permission) for permission in role_config.permissions
        )

    return PermissionPolicy(
        role_permissions=role_permissions,
        superuser_bypass=config.defaults.superuser_bypass,
        missing_workspace=config.defaults.missing_workspace,
        missing_role=config.defaults.missing_role,
    )


def load_permissions_config(
    *,
    config_dir: str | Path | None = None,
) -> PermissionsConfig:
    data = load_yaml_config("access/permissions.yaml", config_dir=config_dir)
    try:
        return PermissionsConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid access permissions config: {exc}") from exc


@lru_cache
def get_permission_policy() -> PermissionPolicy:
    return load_permission_policy()


@lru_cache
def get_permissions_config() -> PermissionsConfig:
    return load_permissions_config()
