"""Task job ORM model.

职责：保存异步任务的类型、状态、进度、参数和失败日志。
边界：本模块不负责任务投递或执行。
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.orm.base import AuditMixin, Base, BaseIdModel


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskJob(Base, BaseIdModel, AuditMixin):
    """异步任务持久化模型。"""

    __tablename__ = "task_jobs"

    action_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[TaskStatus] = mapped_column(
        String(20), index=True, default=TaskStatus.PENDING
    )
    progress: Mapped[int] = mapped_column(default=0)
    payload: Mapped[dict] = mapped_column(JSONB)
    error_log: Mapped[str | None] = mapped_column(Text)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
        comment="提交任务的用户ID",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="任务开始执行时间"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="任务结束时间（完成或失败）"
    )
