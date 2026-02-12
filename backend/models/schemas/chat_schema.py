import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

# --- Reusable Types (提升代码一致性) ---
# 为 B 端系统定义严格的校验规则，防止脏数据穿透到你的 DBA 领地
UsernameStr = Annotated[
    str, Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
]
PasswordStr = Annotated[str, Field(min_length=8, max_length=128)]

# --- Base Schemas ---


class ChatBase(BaseModel):
    """
    所有 User 相关 Schema 的基石。
    只放 API 层最通用的字段。
    """

    username: UsernameStr = Field(..., description="唯一登录名")
    email: EmailStr = Field(..., description="企业联系邮箱")
