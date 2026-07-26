"""Task job and durable dispatch outbox ORM models.

职责：保存异步任务状态、Knowledge worker lease 和持久派发事件。
边界：本模块只声明持久事实，不负责任务投递、执行或恢复编排。
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.orm.base import AuditMixin, Base, BaseIdModel


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskOutboxStatus(StrEnum):
    """Transactional outbox publish state."""

    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    DEAD = "dead"


KNOWLEDGE_INGESTION_EVENT = "knowledge.ingestion.requested"


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

    knowledge_file_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_files.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
        comment="Structured Knowledge file identity; payload is compatibility only",
    )
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
        comment="Worker claims for this durable job",
    )

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
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="当前 worker 最近一次续租时间"
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="当前 worker claim 到期时间"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'canceled')",
            name="status_values",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="attempt_count_non_negative",
        ),
        Index(
            "ix_task_jobs_kb_status_updated",
            "action_type",
            "status",
            "updated_at",
        ),
        Index(
            "ix_task_jobs_kb_lease",
            "action_type",
            "status",
            "lease_expires_at",
        ),
        Index(
            "uq_task_jobs_active_knowledge_file",
            "knowledge_file_id",
            unique=True,
            postgresql_where=text(
                "knowledge_file_id IS NOT NULL "
                "AND action_type = 'KB_INGESTION' "
                "AND status IN ('pending', 'processing')"
            ),
        ),
    )


class TaskOutbox(Base, BaseIdModel, AuditMixin):
    """Durable at-least-once publish record for one task event."""

    __tablename__ = "task_outbox"

    task_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("task_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[TaskOutboxStatus] = mapped_column(
        String(20),
        default=TaskOutboxStatus.PENDING,
        server_default=text("'pending'"),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "event_type",
            name="uq_task_outbox_task_event",
        ),
        CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'dead')",
            name="status_values",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="attempt_count_non_negative",
        ),
        CheckConstraint(
            "status <> 'publishing' OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="publishing_has_lease",
        ),
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="published_has_timestamp",
        ),
        Index(
            "ix_task_outbox_claim",
            "status",
            "next_attempt_at",
            postgresql_where=text("status IN ('pending', 'publishing')"),
        ),
    )
