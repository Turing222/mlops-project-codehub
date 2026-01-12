import uuid
from datetime import datetime

from pydantic import EmailStr
from sqlmodel import Field, SQLModel
from ulid import ULID

#print("DEBUG: 正在读取 models/user.py 文件...") 

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
class UserBase(SQLModel):
    username: str = Field(index=True, unique=True, min_length=3, max_length=20)
    email: EmailStr = Field(unique=True)

# 3. API 输入模型 (Schema)
class UserCreate(UserBase):
    password: str = Field(min_length=8)

# 4. API 输出模型 (Schema)
# 这里需要 ID，所以它同时继承 UserBase 和 BaseIdModel，但 table=False
class UserPublic(UserBase):
    id: uuid.UUID

class User(BaseIdModel,UserBase, table=True):
    __tablename__ = 'user'
    old_id: int | None 
    # 甚至可以从 ID 中反推创建时间（ULID 特性）
    @property
    def created_at_from_id(self) -> datetime:
        return ULID.from_uuid(self.id).datetime

#print(f"DEBUG: User 类定义完毕。当前 SQLModel.metadata.tables keys: {list(SQLModel.metadata.tables.keys())}") # <--- 添加这行
