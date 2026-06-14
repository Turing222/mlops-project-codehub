"""User ORM model.

职责：定义账号、登录凭据、额度和用户侧反向关系。
边界：本模块不处理密码哈希、认证或权限判定。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.orm.base import AuditMixin, Base, BaseIdModel

if TYPE_CHECKING:
    from backend.models.orm.access import AuditEvent, UserWorkspaceRole, Workspace
    from backend.models.orm.chat import ChatSession
    from backend.models.orm.knowledge import KnowledgeBase


class User(Base, BaseIdModel, AuditMixin):
    """用户账号持久化模型。"""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False, comment="B端登录唯一标识"
    )
    email: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    phone: Mapped[str | None] = mapped_column(
        String(20),
        unique=True,
        index=True,
        nullable=True,
        comment="手机号（短信登录标识）",
    )
    auth_provider: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        server_default=text("'local'"),
        comment="注册渠道: local/phone/google",
    )
    google_sub: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, comment="Google OAuth sub 声明"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )

    max_tokens: Mapped[int] = mapped_column(
        default=100000, server_default=text("100000"), comment="用户 Token 总额度"
    )
    used_tokens: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), comment="用户已消费 Token 数"
    )

    # 哈希密码只允许在鉴权链路使用，响应 schema 不暴露该字段。
    # 手机号/Google 登录用户可能没有密码，因此 nullable。
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sessions: Mapped[list[ChatSession]] = relationship(back_populates="user")
    knowledge_bases: Mapped[list[KnowledgeBase]] = relationship(back_populates="user")
    owned_workspaces: Mapped[list[Workspace]] = relationship(
        back_populates="owner",
        foreign_keys="Workspace.owner_id",
    )
    workspace_roles: Mapped[list[UserWorkspaceRole]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="actor")
