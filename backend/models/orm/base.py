import uuid
from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from ulid import ULID
import pgvector.sqlalchemy

# 1. 定义一个通用的类型注解，方便全系统统一修改规格
# 例如：将来想把所有时间戳改为带时区的，只需改这里
timestamp = Annotated[
    datetime, mapped_column(DateTime(timezone=True), server_default=func.now())
]

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "%(table_name)s_pkey",
}


class IDGenerator:
    """ID 生成器工具"""

    @staticmethod
    def new_ulid_as_uuid() -> uuid.UUID:
        return ULID().to_uuid()


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming_convention)
    """所有模型的祖先类"""

    pass


class BaseIdModel:
    """
    基础 ID 模型
    使用 ULID -> UUID 的方案。
    作为 DBA，你一定知道 K-Ordered (按时间排序) 的 ID 对 B-Tree 索引非常友好，
    能极大减少索引分裂（Index Fragmentation）。
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),  # 显式指定存储类型
        primary_key=True,
        # 这里使用 default 而非 server_default，是因为 ULID 通常由应用层生成
        default=IDGenerator.new_ulid_as_uuid,
        # 显式指定 SQL 类型，确保跨库一致性
        nullable=False,
        comment="基于ULID生成的唯一标识",
        server_default=text("gen_random_uuid()"),  # 数据库侧的兜底逻辑
    )


class AuditMixin:
    # 1. 使用 datetime 类型
    # 2. sort_order=999 确保这些审计字段在建表时排在最后（可选）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),  # 建议开启时区支持
        server_default=func.now(),
        comment="创建时间",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # 初始时更新时间等于创建时间
        onupdate=func.now(),  # 应用层触发更新
        comment="最后更新时间",
    )
