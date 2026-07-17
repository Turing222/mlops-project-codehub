"""Chat session and message ORM models.

职责：定义对话会话、消息内容、幂等键和 RAG 溯源字段。
边界：本模块不负责消息生成、权限校验或上下文拼装。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.enums import ChatGenerationStatus, MessageStatus
from backend.models.orm.base import AuditMixin, Base, BaseIdModel, SoftDeleteMixin

if TYPE_CHECKING:
    from backend.models.orm.access import Workspace
    from backend.models.orm.chunk import DocumentChunk
    from backend.models.orm.user import User


class ChatSession(Base, BaseIdModel, AuditMixin, SoftDeleteMixin):
    """对话会话，作为消息分组和 LLM 配置容器。"""

    __tablename__ = "chat_sessions"

    title: Mapped[str] = mapped_column(String(255), default="新对话")
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kb_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    llm_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))
    context_state: Mapped[dict] = mapped_column(
        JSONB,
        server_default=text("'{}'"),
        nullable=False,
    )
    context_state_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="sessions")
    workspace: Mapped[Workspace | None] = relationship(back_populates="chat_sessions")
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),)


class ChatMessage(Base, BaseIdModel, AuditMixin):
    """单条对话消息。"""

    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")
    user: Mapped[User | None] = relationship()

    status: Mapped[MessageStatus] = mapped_column(
        String(20), default=MessageStatus.THINKING
    )

    # 保存检索命中的 chunk 和距离，供前端展示引用来源。
    search_context: Mapped[dict | None] = mapped_column(
        JSONB, comment="存储 RAG 检索到的原始分块信息"
    )
    message_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        server_default=text("'{}'"),
        nullable=False,
    )

    client_request_id: Mapped[str | None] = mapped_column(
        String(64), comment="客户端生成的唯一请求 ID"
    )

    tokens_input: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), comment="输入 Token 数"
    )
    tokens_output: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), comment="输出 Token 数"
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_msgs_session_created", "session_id", "created_at"),
        # 只在提供幂等键时约束唯一性，避免多条 NULL 消息互相冲突。
        Index(
            "idx_msgs_client_req_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
    )

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )


class ChatGenerationRequest(Base, BaseIdModel, AuditMixin):
    """Durable identity and current attempt state for one Chat generation."""

    __tablename__ = "chat_generation_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    assistant_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    client_request_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Actor-scoped idempotency identity supplied by the client",
    )
    task_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Latest broker task identity for the current attempt",
    )
    status: Mapped[ChatGenerationStatus] = mapped_column(
        String(20),
        default=ChatGenerationStatus.PREPARED,
        server_default=text("'prepared'"),
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
    )
    dispatch_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
        comment="Broker dispatch reservations for the current business attempt",
    )
    dispatch_context: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Validated Worker inputs for durable redispatch; no secrets",
    )
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reserved_credits: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    retryable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Sanitized terminal message; never store raw provider payloads",
    )

    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "client_request_id",
            name="uq_chat_generation_requests_user_client_request",
        ),
        CheckConstraint(
            "length(btrim(client_request_id)) > 0",
            name="client_request_id_not_blank",
        ),
        CheckConstraint(
            "status IN ('prepared', 'queued', 'running', 'succeeded', 'failed')",
            name="status_values",
        ),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        CheckConstraint(
            "dispatch_attempts >= 0",
            name="dispatch_attempts_non_negative",
        ),
        CheckConstraint(
            "reserved_credits >= 0",
            name="reserved_credits_non_negative",
        ),
        CheckConstraint(
            "status = 'failed' OR retryable = false",
            name="retryable_only_when_failed",
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'failed') AND finished_at IS NOT NULL) "
            "OR (status NOT IN ('succeeded', 'failed') AND finished_at IS NULL)",
            name="terminal_finished_at",
        ),
        CheckConstraint(
            "status <> 'failed' OR length(btrim(error_code)) > 0",
            name="failed_error_code",
        ),
        CheckConstraint(
            "status <> 'succeeded' OR assistant_message_id IS NOT NULL",
            name="succeeded_assistant_message",
        ),
        CheckConstraint(
            "status NOT IN ('queued', 'running') "
            "OR (length(btrim(task_id)) > 0 AND length(btrim(lease_token)) > 0)",
            name="active_attempt_fence",
        ),
        Index(
            "uq_chat_generation_requests_user_message",
            "user_message_id",
            unique=True,
            postgresql_where=text("user_message_id IS NOT NULL"),
        ),
        Index(
            "uq_chat_generation_requests_assistant_message",
            "assistant_message_id",
            unique=True,
            postgresql_where=text("assistant_message_id IS NOT NULL"),
        ),
        Index(
            "uq_chat_generation_requests_task",
            "task_id",
            unique=True,
            postgresql_where=text("task_id IS NOT NULL"),
        ),
        Index(
            "ix_chat_generation_requests_session_created",
            "session_id",
            "created_at",
        ),
        Index(
            "ix_chat_generation_requests_recovery_due",
            "status",
            "recovery_due_at",
            postgresql_where=text("recovery_due_at IS NOT NULL"),
        ),
    )
