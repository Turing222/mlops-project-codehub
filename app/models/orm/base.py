import uuid
from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from ulid import ULID

# 1. 定义一个通用的类型注解，方便全系统统一修改规格
# 例如：将来想把所有时间戳改为带时区的，只需改这里
timestamp = Annotated[
    datetime, mapped_column(DateTime(timezone=True), server_default=func.now())
]


class IDGenerator:
    """ID 生成器工具"""

    @staticmethod
    def new_ulid_as_uuid() -> uuid.UUID:
        return ULID().to_uuid()


class Base(DeclarativeBase):
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
        primary_key=True,
        # 这里使用 default 而非 server_default，是因为 ULID 通常由应用层生成
        default=IDGenerator.new_ulid_as_uuid,
        # 显式指定 SQL 类型，确保跨库一致性
        index=True,
        nullable=False,
        comment="基于ULID生成的唯一标识",
    )


class AuditMixin:
    """
    审计混合类
    """

    # 使用 server_default 确保 DB 层面有默认值
    created_at: Mapped[timestamp] = mapped_column(comment="创建时间")

    # onupdate 由 SQLAlchemy 在应用层触发
    # server_onupdate 可以由数据库触发（取决于 DB 支持）
    updated_at: Mapped[timestamp] = mapped_column(
        onupdate=func.now(), comment="最后更新时间"
    )
