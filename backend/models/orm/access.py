from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.orm.base import AuditMixin, Base, BaseIdModel

if TYPE_CHECKING:
    from backend.models.orm.chat import ChatSession
    from backend.models.orm.knowledge import File, KnowledgeBase
    from backend.models.orm.user import User


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


class Workspace(Base, BaseIdModel, AuditMixin):
    """权限隔离的工作区。"""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # R7 修复：软删除字段。NULL 表示活跃，非 NULL 表示已删除。
    # 使用软删除保留 KB/File/ChatSession 等关联数据，
    # 防止删除 Workspace 导致子资源孤立（workspace_id 被置 NULL）。
    deleted_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="软删除时间，NULL 表示活跃",
    )

    owner: Mapped[User | None] = relationship(
        back_populates="owned_workspaces",
        foreign_keys=[owner_id],
    )
    user_roles: Mapped[list[UserWorkspaceRole]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    knowledge_bases: Mapped[list[KnowledgeBase]] = relationship(
        back_populates="workspace",
    )
    files: Mapped[list[File]] = relationship(back_populates="workspace")
    chat_sessions: Mapped[list[ChatSession]] = relationship(back_populates="workspace")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="workspace")


class UserWorkspaceRole(Base, BaseIdModel, AuditMixin):
    """用户在某个工作区中的角色。"""

    __tablename__ = "user_workspace_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        String(20),
        default=WorkspaceRole.MEMBER,
        server_default=WorkspaceRole.MEMBER,
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="workspace_roles")
    workspace: Mapped[Workspace] = relationship(back_populates="user_roles")

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            name="uq_user_workspace_roles_user_workspace",
        ),
    )


class AuditEvent(Base, BaseIdModel, AuditMixin):
    """基础审计事件，记录关键写操作、鉴权拒绝和安全相关事件。"""

    __tablename__ = "audit_events"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(index=True, nullable=True)
    outcome: Mapped[AuditOutcome] = mapped_column(
        String(20),
        default=AuditOutcome.SUCCESS,
        server_default=AuditOutcome.SUCCESS,
        nullable=False,
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        server_default=text("'{}'"),
        nullable=False,
    )

    actor: Mapped[User | None] = relationship(back_populates="audit_events")
    workspace: Mapped[Workspace | None] = relationship(back_populates="audit_events")

    __table_args__ = (
        Index("idx_audit_events_workspace_created", "workspace_id", "created_at"),
        Index("idx_audit_events_actor_created", "actor_user_id", "created_at"),
    )
