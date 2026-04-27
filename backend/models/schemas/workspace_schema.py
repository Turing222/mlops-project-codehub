import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.models.orm.access import WorkspaceRole

WorkspaceNameStr = Annotated[str, Field(min_length=1, max_length=100)]
WorkspaceSlugStr = Annotated[
    str,
    Field(min_length=3, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]$"),
]


class WorkspaceCreate(BaseModel):
    name: WorkspaceNameStr
    slug: WorkspaceSlugStr

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.lower()


class WorkspaceUpdate(BaseModel):
    name: WorkspaceNameStr | None = None
    slug: WorkspaceSlugStr | None = None

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str | None) -> str | None:
        return value.lower() if value else value

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> Self:
        if self.name is None and self.slug is None:
            raise ValueError("至少需要提供一个要更新的字段")
        return self


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    owner_id: uuid.UUID | None = None
    current_user_role: WorkspaceRole | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceListResponse(BaseModel):
    items: list[WorkspaceResponse]
    total: int = Field(..., ge=0)
    skip: int = Field(..., ge=0)
    limit: int = Field(..., ge=1)


class WorkspaceMemberCreate(BaseModel):
    user_id: uuid.UUID
    role: WorkspaceRole = WorkspaceRole.MEMBER

    model_config = ConfigDict(extra="forbid")


class WorkspaceMemberUpdate(BaseModel):
    role: WorkspaceRole

    model_config = ConfigDict(extra="forbid")


class WorkspaceMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    username: str
    email: str
    role: WorkspaceRole
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceMemberListResponse(BaseModel):
    items: list[WorkspaceMemberResponse]
    total: int = Field(..., ge=0)
    skip: int = Field(..., ge=0)
    limit: int = Field(..., ge=1)
