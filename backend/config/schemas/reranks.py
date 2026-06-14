"""Rerank models config schema.

职责：定义 llm/models.yaml 中 reranks 段的 Pydantic schema 及校验。
边界：本模块不创建 rerank 客户端，不解析 API key 环境变量。
失败处理：default_profile 缺失、alias 冲突时抛出 ValidationError。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.config.schemas._validators import (
    check_alias_conflicts,
    validate_non_empty_string,
    validate_unique_non_empty_list,
)


class RerankModelProfile(BaseModel):
    """单个 rerank provider profile。"""

    provider: str
    model: str
    base_url: str | None = None
    api_key_envs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    score_kind: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", "model")
    @classmethod
    def validate_required_string(cls, value: str) -> str:
        return validate_non_empty_string(value)

    @field_validator("aliases", "api_key_envs")
    @classmethod
    def validate_string_list(cls, values: list[str]) -> list[str]:
        return validate_unique_non_empty_list(values)


class RerankModelsConfig(BaseModel):
    """rerank profile 配置集合。"""

    default_profile: str
    profiles: dict[str, RerankModelProfile]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_profiles(self) -> "RerankModelsConfig":
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"rerank default_profile {self.default_profile!r} is not defined "
                "in profiles"
            )

        check_alias_conflicts(self.profiles, label="Rerank profile")

        return self
