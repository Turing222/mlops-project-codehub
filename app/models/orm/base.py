import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel, text
from ulid import ULID
from sqlalchemy import Column, DateTime


class IDGenerator:
    """ID 生成器工具"""

    @staticmethod
    def new_ulid_as_uuid() -> uuid.UUID:
        return ULID().to_uuid()


class BaseIdModel(SQLModel):
    """基础 ID 模型"""

    id: uuid.UUID = Field(
        default_factory=IDGenerator.new_ulid_as_uuid,
        primary_key=True,
        index=True,
        nullable=False,
    )


class AuditMixin(SQLModel):
    """
    审计混合类：自动处理创建时间和更新时间
    注意：在 PostgreSQL 中建议配置 server_default=func.now()
    但在 SQLModel 层面这里提供了基础支持。
    """

    created_at: datetime = Field(
        sa_column=Column(
            DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
        )
    )

    # 2. 更新时间：Python/SQLAlchemy 层面自动触发
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            onupdate=datetime.now,  # 每次 ORM 更新时调用此函数 函数引用
        )
    )
