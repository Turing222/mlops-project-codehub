from pydantic import BaseModel, EmailStr
from typing import Optional

# 所有的核心共有字段
class UserBase(BaseModel):
    username: str
    email: EmailStr

# 用于注册：需要密码，但不一定有 ID
class UserCreate(UserBase):
    password: str 

# 用于返回：没有密码，但一定有 ID
class UserPublic(UserBase):
    id: int

    class Config:
        from_attributes = True # 关键：允许从 SQLModel/ORM 对象转换