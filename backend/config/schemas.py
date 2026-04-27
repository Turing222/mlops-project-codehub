from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.models.orm.access import WorkspaceRole
from backend.services.permission_types import Permission


class PermissionDefinition(BaseModel):
    description: str = ""

    model_config = ConfigDict(extra="forbid")


class RoleDefinition(BaseModel):
    permissions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PermissionDefaults(BaseModel):
    superuser_bypass: bool = True
    missing_workspace: Literal["allow", "deny"] = "deny"
    missing_role: Literal["allow", "deny"] = "deny"

    model_config = ConfigDict(extra="forbid")


class PermissionsConfig(BaseModel):
    version: int = 1
    permissions: dict[str, PermissionDefinition]
    roles: dict[str, RoleDefinition]
    defaults: PermissionDefaults = Field(default_factory=PermissionDefaults)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_policy(self) -> "PermissionsConfig":
        known_permissions = {permission.value for permission in Permission}
        configured_permissions = set(self.permissions)
        unknown_permissions = configured_permissions - known_permissions
        if unknown_permissions:
            raise ValueError(
                "Unknown permissions in permissions.yaml: "
                f"{sorted(unknown_permissions)}"
            )

        missing_permissions = known_permissions - configured_permissions
        if missing_permissions:
            raise ValueError(
                "permissions.yaml must document every code permission; missing: "
                f"{sorted(missing_permissions)}"
            )

        known_roles = {role.value for role in WorkspaceRole}
        configured_roles = set(self.roles)
        unknown_roles = configured_roles - known_roles
        if unknown_roles:
            raise ValueError(
                f"Unknown roles in permissions.yaml: {sorted(unknown_roles)}"
            )

        missing_roles = known_roles - configured_roles
        if missing_roles:
            raise ValueError(
                f"permissions.yaml must configure every workspace role; missing: "
                f"{sorted(missing_roles)}"
            )

        for role_name, role_config in self.roles.items():
            permissions = role_config.permissions
            if not permissions:
                raise ValueError(f"Role {role_name!r} must define permissions")
            if "*" in permissions and len(permissions) > 1:
                raise ValueError(
                    f"Role {role_name!r} cannot combine '*' with explicit permissions"
                )
            unknown_role_permissions = set(permissions) - known_permissions - {"*"}
            if unknown_role_permissions:
                raise ValueError(
                    f"Role {role_name!r} references unknown permissions: "
                    f"{sorted(unknown_role_permissions)}"
                )

        return self


class PromptTemplateDefinition(BaseModel):
    content: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt template content must not be empty")
        return value


class PromptDefaults(BaseModel):
    variables: dict[str, object] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class PromptSource(BaseModel):
    provider: Literal["yaml", "langfuse_cache"] = "yaml"
    label: str = "production"
    ttl_seconds: int = Field(default=300, ge=0)
    cache_path: str = ".cache/langfuse/prompts.production.yaml"
    fallback: Literal["yaml", "none"] = "yaml"
    synced_at: str | None = None

    model_config = ConfigDict(extra="forbid")


class LangfusePromptDefinition(BaseModel):
    name: str
    type: Literal["text", "chat"] = "text"
    version: int | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Langfuse prompt name must not be empty")
        return value.strip()


class LangfusePromptConfig(BaseModel):
    templates: dict[str, LangfusePromptDefinition] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class PromptsConfig(BaseModel):
    version: int = 1
    source: PromptSource = Field(default_factory=PromptSource)
    langfuse: LangfusePromptConfig = Field(default_factory=LangfusePromptConfig)
    defaults: PromptDefaults = Field(default_factory=PromptDefaults)
    templates: dict[str, PromptTemplateDefinition]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_required_templates(self) -> "PromptsConfig":
        required_templates = {"default_system", "rag_system", "summarize"}
        missing_templates = required_templates - set(self.templates)
        if missing_templates:
            raise ValueError(
                f"prompts.yaml must define templates: {sorted(missing_templates)}"
            )
        if self.source.provider == "langfuse_cache":
            missing_langfuse_templates = required_templates - set(
                self.langfuse.templates
            )
            if missing_langfuse_templates:
                raise ValueError(
                    "prompts.yaml must define Langfuse mappings for templates: "
                    f"{sorted(missing_langfuse_templates)}"
                )
        return self


class LLMModelProfile(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key_envs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", "model")
    @classmethod
    def validate_required_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be empty")
        return value.strip()

    @field_validator("aliases", "api_key_envs")
    @classmethod
    def validate_string_list(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("Values must be unique")
        return cleaned


class LLMModelRoute(BaseModel):
    profiles: list[str] = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("profiles", "aliases")
    @classmethod
    def validate_string_list(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("Values must be unique")
        return cleaned


class EmbeddingModelProfile(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key_envs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    dimensions: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", "model")
    @classmethod
    def validate_required_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be empty")
        return value.strip()

    @field_validator("aliases", "api_key_envs")
    @classmethod
    def validate_string_list(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("Values must be unique")
        return cleaned


class EmbeddingModelsConfig(BaseModel):
    default_profile: str
    profiles: dict[str, EmbeddingModelProfile]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_profiles(self) -> "EmbeddingModelsConfig":
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"embedding default_profile {self.default_profile!r} is not defined "
                "in profiles"
            )

        seen_aliases: dict[str, str] = {}
        for profile_name, profile in self.profiles.items():
            identifiers = [profile_name, *profile.aliases]
            for identifier in identifiers:
                normalized = identifier.strip().lower()
                if not normalized:
                    raise ValueError("Embedding profile aliases must not be empty")
                existing = seen_aliases.get(normalized)
                if existing and existing != profile_name:
                    raise ValueError(
                        f"Embedding profile alias {identifier!r} is used by both "
                        f"{existing!r} and {profile_name!r}"
                    )
                seen_aliases[normalized] = profile_name

        return self


class LLMModelsConfig(BaseModel):
    version: int = 1
    default_profile: str
    profiles: dict[str, LLMModelProfile]
    routes: dict[str, LLMModelRoute] = Field(default_factory=dict)
    embeddings: EmbeddingModelsConfig | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_profiles(self) -> "LLMModelsConfig":
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"default_profile {self.default_profile!r} is not defined in profiles"
            )

        seen_aliases: dict[str, str] = {}
        for profile_name, profile in self.profiles.items():
            identifiers = [profile_name, *profile.aliases]
            for identifier in identifiers:
                normalized = identifier.strip().lower()
                if not normalized:
                    raise ValueError("Profile aliases must not be empty")
                existing = seen_aliases.get(normalized)
                if existing and existing != profile_name:
                    raise ValueError(
                        f"LLM profile alias {identifier!r} is used by both "
                        f"{existing!r} and {profile_name!r}"
                    )
                seen_aliases[normalized] = profile_name

        for route_name, route in self.routes.items():
            for profile_name in route.profiles:
                if profile_name not in self.profiles:
                    raise ValueError(
                        f"LLM route {route_name!r} references unknown profile "
                        f"{profile_name!r}"
                    )

            identifiers = [route_name, *route.aliases]
            for identifier in identifiers:
                normalized = identifier.strip().lower()
                if not normalized:
                    raise ValueError("Route aliases must not be empty")
                existing = seen_aliases.get(normalized)
                if existing and existing != route_name:
                    raise ValueError(
                        f"LLM route alias {identifier!r} conflicts with {existing!r}"
                    )
                seen_aliases[normalized] = route_name

        return self
