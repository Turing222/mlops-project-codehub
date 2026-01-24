from pydantic import EmailStr
from sqlmodel import Field, SQLModel

from app.models.orm.base import AuditMixin, BaseIdModel


# 定义 User 独有的基础字段，供 ORM 和 Schema 复用
class UserBase(SQLModel):
    username: str = Field(index=True, unique=True, min_length=3, max_length=20)
    email: EmailStr = Field(unique=True, index=True)
    is_active: bool = Field(default=True)  # 登录/权限控制用
    is_superuser: bool = Field(default=False)  # 权限控制用


class User(BaseIdModel, AuditMixin, UserBase, table=True):
    __tablename__ = "users"

    # 敏感字段：哈希后的密码，不需要在 UserBase 里出现
    hashed_password: str = Field(nullable=False)

    # 将来可以在这里加 relationship
    # roles: List["Role"] = Relationship(...)
