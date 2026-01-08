import uuid
from datetime import datetime

from pydantic import EmailStr
from sqlmodel import Field, SQLModel
from ulid import ULID


# 1. 封装 ID 生成器类，方便统一管理和 Mock 测试
class IDGenerator:
    @staticmethod
    def new_ulid_as_uuid() -> uuid.UUID:
        """生成 ULID 并转换为 UUID 格式供 DB 存储"""
        return ULID().to_uuid()
    
# 2. 定义基础模型（Base Model）
class BaseIdModel(SQLModel):
    # 使用 default_factory 确保每次实例化生成新 ID
    id: uuid.UUID = Field(
        default_factory=IDGenerator.new_ulid_as_uuid,
        primary_key=True
    )

class User_new(BaseIdModel, table=True):
    # 限制长度
    username: str = Field(index=True, unique=True, min_length=3, max_length=20)
    # 严格校验邮箱格式 (需要安装 email-validator)
    email: EmailStr = Field(unique=True)
    old_id: int | None 
    
    # 甚至可以从 ID 中反推创建时间（ULID 特性）
    @property
    def created_at_from_id(self) -> datetime:
        return ULID.from_uuid(self.id).datetime

class User(SQLModel, table=True):
    id: int | None = Field(
        default=None, 
        primary_key=True)
    # 限制长度
    username: str = Field(index=True, unique=True, min_length=3, max_length=20)
    # 严格校验邮箱格式 (需要安装 email-validator)
    email: EmailStr = Field(unique=True)