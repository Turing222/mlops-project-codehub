"""LLM models YAML config schema.

职责：定义 llm/models.yaml 的 Pydantic schema 及跨字段校验。
边界：本模块不创建 provider 客户端，不解析 API key 环境变量。
失败处理：default_profile 缺失、alias 冲突、route 引用未知 profile 时抛出 ValidationError。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.config.schemas._validators import (
    check_alias_conflicts,
    validate_non_empty_string,
    validate_unique_non_empty_list,
)
from backend.config.schemas.embeddings import EmbeddingModelsConfig
from backend.config.schemas.reranks import RerankModelsConfig
from backend.models.schemas.chat.params import LLMExtraBody


class LLMModelProfile(BaseModel):
    """单个 LLM provider profile。"""

    provider: str
    model: str
    base_url: str | None = None
    api_key_envs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    extra_body: LLMExtraBody | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", "model")
    @classmethod
    def validate_required_string(cls, value: str) -> str:
        return validate_non_empty_string(value)

    @field_validator("aliases", "api_key_envs")
    @classmethod
    def validate_string_list(cls, values: list[str]) -> list[str]:
        return validate_unique_non_empty_list(values)


class LLMModelRoute(BaseModel):
    """一组按顺序尝试的 LLM profile。"""

    profiles: list[str] = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("profiles", "aliases")
    @classmethod
    def validate_string_list(cls, values: list[str]) -> list[str]:
        return validate_unique_non_empty_list(values)


class LLMModelsConfig(BaseModel):
    """llm/models.yaml 的完整 schema。"""

    version: int = 1
    default_profile: str
    profiles: dict[str, LLMModelProfile]
    routes: dict[str, LLMModelRoute] = Field(default_factory=dict)
    embeddings: EmbeddingModelsConfig | None = None
    reranks: RerankModelsConfig | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_profiles(self) -> "LLMModelsConfig":
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"default_profile {self.default_profile!r} is not defined in profiles"
            )

        check_alias_conflicts(self.profiles, label="LLM profile")

        # 收集 profile alias 映射用于 route 的跨类型冲突检测
        seen_aliases: dict[str, str] = {}
        for profile_name, profile in self.profiles.items():
            for identifier in (profile_name, *profile.aliases):
                seen_aliases[identifier.strip().lower()] = profile_name

        for route_name, route in self.routes.items():
            for profile_name in route.profiles:
                if profile_name not in self.profiles:
                    raise ValueError(
                        f"LLM route {route_name!r} references unknown profile "
                        f"{profile_name!r}"
                    )

            for identifier in (route_name, *route.aliases):
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
