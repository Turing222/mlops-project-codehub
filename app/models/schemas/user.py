import uuid
from datetime import datetime

from pydantic import EmailStr
from sqlmodel import SQLModel

from app.models.orm.user import UserBase

# --- Request Schemas (请求参数) ---


class UserCreate(UserBase):
    """注册/创建用户时的参数"""

    password: str  # 这里接收明文密码，Service 层负责 Hash
    # 创建时不需要传 is_active/is_superuser，使用默认值，或者单独定义 AdminCreate


class UserUpdate(SQLModel):
    """更新用户时的参数，所有字段可选"""

    username: str | None = None
    email: EmailStr | None = None
    password: str | None = None
    is_active: bool | None = None


# --- Response Schemas (返回结果) ---


class UserPublic(UserBase):
    """返回给前端的用户信息（不包含密码）"""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    # 允许从 ORM 对象读取数据
    model_config = {"from_attributes": True}


# --- Auth Schemas (登录相关) ---


class Token(SQLModel):
    access_token: str
    token_type: str
