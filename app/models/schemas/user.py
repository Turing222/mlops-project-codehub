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


class UserBase(BaseModel):
    """
    所有 User 相关 Schema 的基石。
    只放 API 层最通用的字段。
    """

    username: UsernameStr = Field(..., description="唯一登录名")
    email: EmailStr = Field(..., description="企业联系邮箱")


# --- Request Schemas (输入控制) ---


class UserSearch(BaseModel):
    """专门用于通过单一标识符查询用户的 Schema"""

    username: UsernameStr | None = None
    email: EmailStr | None = None

    @model_validator(mode="after")
    def check_at_least_one(self) -> Self:
        # DBA 逻辑：确保查询条件不为空，否则会变成全表扫描或逻辑错误
        if not self.username and not self.email:
            raise ValueError("必须提供 username 或 email 其中之一进行查询")

        # 面试加分点：如果业务要求只能二选一，不准同时传
        # if self.username and self.email:
        #    raise ValueError("只能选择一种查询方式（username 或 email），不能同时提供")

        return self


class UserLogin(BaseModel):
    """专门用于登录 Schema"""

    username: UsernameStr = Field(...)
    password: PasswordStr = Field(...)


class UserCreate(UserBase):
    # 1. 第一层：使用 Annotated/Field 处理基础规格

    password: PasswordStr = Field(...)
    confirm_password: PasswordStr = Field(...)

    # 2. 第二层：使用 @field_validator 处理特定字段逻辑
    @field_validator("username")
    @classmethod
    def username_not_reserved(cls, v: str) -> str:
        reserved_names = {"admin", "root", "system", "superuser"}
        if v.lower() in reserved_names:
            raise ValueError("该用户名已被系统预留")
        return v.lower()  # 顺便做标准化处理：统一转小写

    # 3. 第三层：使用 @model_validator 处理跨字段校验
    @model_validator(mode="after")
    def check_passwords_match(self) -> Self:
        if self.password != self.confirm_password:
            # 这种错误会抛出 422 Unprocessable Entity
            raise ValueError("两次输入的密码不一致")
        return self

    model_config = ConfigDict(str_strip_whitespace=True)  # 自动去除字符串前后空格


class UserUpdate(BaseModel):
    """
    PATCH 场景：所有字段必须为 Optional。
    注意：这里不继承 UserBase，因为 Update 往往不需要强制传所有字段。
    """

    username: UsernameStr | None = None
    email: EmailStr | None = None
    password: PasswordStr | None = None
    is_active: bool | None = None

    model_config = ConfigDict(
        str_strip_whitespace=True,
        from_attributes=True,
        extra="forbid",  # 面试加分项：禁止前端传入定义的字段之外的多余参数（防止注入攻击）
    )


# --- Response Schemas (输出控制) ---


class UserResponse(UserBase):
    """
    标准响应对象。
    1. 包含 ID (UUID)
    2. 包含审计时间戳
    3. 包含权限状态（B2B 核心）
    """

    id: uuid.UUID
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime

    # Pydantic v2 的标准写法，取代旧的 model_config = {...}
    model_config = ConfigDict(from_attributes=True)


# --- Auth Schemas ---


class Token(BaseModel):
    """不再使用 SQLModel，保持 Schema 层纯粹"""

    access_token: str
    token_type: str = "bearer"
