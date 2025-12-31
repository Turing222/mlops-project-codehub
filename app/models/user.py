from pydantic import EmailStr
from sqlmodel import Field, SQLModel
from typing import Optional

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # 限制长度
    username: str = Field(index=True, unique=True, min_length=3, max_length=20)
    # 严格校验邮箱格式 (需要安装 email-validator)
    email: EmailStr = Field(unique=True)