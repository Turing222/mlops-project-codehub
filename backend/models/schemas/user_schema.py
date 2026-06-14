"""User request and response schemas.

职责：定义用户注册、登录、更新、导入和响应的 Pydantic 模型。
边界：本模块只做输入输出校验，不处理密码哈希或数据库访问。
"""

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

UsernameStr = Annotated[
    str, Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
]
PasswordStr = Annotated[str, Field(min_length=8, max_length=128)]


class UserBase(BaseModel):
    """用户 schema 的公共字段。"""

    username: UsernameStr = Field(...)
    email: EmailStr | None = None


class UserSearch(BaseModel):
    """按用户名或邮箱查询用户的请求参数。"""

    username: UsernameStr | None = Field(
        None, description="登录名和邮箱必须至少提供一个"
    )
    email: EmailStr | None = Field(None, description="登录名和邮箱必须至少提供一个")

    @model_validator(mode="after")
    def check_at_least_one(self) -> Self:
        # 避免调用方不带条件触发无意义的用户查询。
        if not self.username and not self.email:
            raise ValueError("必须提供 username 或 email 其中之一进行查询")

        return self


class UserLogin(BaseModel):
    """用户登录请求。"""

    username: UsernameStr = Field(...)
    password: PasswordStr = Field(...)


class SMSSendRequest(BaseModel):
    """发送短信验证码请求。"""

    phone: str = Field(
        ..., pattern=r"^\+?\d{7,15}$", description="手机号（含可选国际区号）"
    )


class PhoneLoginRequest(BaseModel):
    """手机号 + 验证码登录请求。"""

    phone: str = Field(..., pattern=r"^\+?\d{7,15}$", description="手机号")
    code: str = Field(..., min_length=4, max_length=6, description="短信验证码")


class GoogleCallbackRequest(BaseModel):
    """Google OAuth 授权码回调请求。"""

    code: str = Field(..., min_length=1, description="Google 返回的授权码")
    redirect_uri: str = Field(..., description="授权请求中使用的回调地址")


class SMSSendResponse(BaseModel):
    """发送短信验证码响应。"""

    message: str


class GoogleAuthUrlResponse(BaseModel):
    """Google OAuth2 授权 URL 响应。"""

    url: str


class UserCreate(UserBase):
    """用户创建请求。"""

    email: EmailStr | None = None
    password: PasswordStr | None = None
    confirm_password: PasswordStr | None = None
    phone: str | None = None
    max_tokens: int = Field(
        default=100000, ge=0, description="用户可使用的最大 Token 额度"
    )

    @field_validator("username")
    @classmethod
    def username_not_reserved(cls, v: str) -> str:
        reserved_names = {"admin", "root", "system", "superuser"}
        if v.lower() in reserved_names:
            raise ValueError("该用户名已被系统预留")
        return v.lower()

    @model_validator(mode="after")
    def check_passwords_match(self) -> Self:
        if (
            self.password is not None
            and self.confirm_password is not None
            and self.password != self.confirm_password
        ):
            raise ValueError("两次输入的密码不一致")
        return self

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class UserUpdate(BaseModel):
    """用户局部更新请求。"""

    username: UsernameStr | None = None
    email: EmailStr | None = None
    phone: str | None = None
    is_active: bool | None = None
    max_tokens: int | None = None

    model_config = ConfigDict(
        str_strip_whitespace=True,
        from_attributes=True,
        extra="forbid",
    )


class UserResponse(UserBase):
    """用户响应对象。"""

    email: EmailStr | None = None
    phone: str | None = None
    auth_provider: str | None = None
    id: uuid.UUID
    is_active: bool
    is_superuser: bool
    max_tokens: int
    used_tokens: int
    features: dict[str, bool] = Field(
        default_factory=dict, description="用户可享有的功能标志字典"
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserImportResponse(BaseModel):
    """批量导入用户响应"""

    filename: str
    total_rows: int
    imported_rows: int
    message: str


class UserProfileUpdate(BaseModel):
    """用户个人信息更新请求（安全隔离，仅限基本信息）。"""

    username: UsernameStr | None = None
    email: EmailStr | None = None
    phone: str | None = None

    model_config = ConfigDict(
        str_strip_whitespace=True,
        from_attributes=True,
        extra="forbid",
    )


class Token(BaseModel):
    """访问令牌响应。"""

    access_token: str
    token_type: str = "bearer"  # noqa: S105
