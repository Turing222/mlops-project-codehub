"""Credits ORM models.

职责：定义 Credits 账户、交易流水、以及 LLM 使用记录的数据库表结构。
边界：本模块仅定义表结构与字段映射，不包含额度消费或变动逻辑。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.orm.base import AuditMixin, Base, BaseIdModel

if TYPE_CHECKING:
    from backend.models.orm.chat import ChatMessage
    from backend.models.orm.user import User


class CreditAccount(Base, BaseIdModel, AuditMixin):
    """Credits 账户，记录用户当前的积分/额度余额。"""

    __tablename__ = "credit_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="关联的用户ID",
    )
    balance: Mapped[int] = mapped_column(
        default=0,
        server_default=text("0"),
        nullable=False,
        comment="Credits 余额(以最小单位记，防精度丢失)",
    )

    user: Mapped[User] = relationship()
    transactions: Mapped[list[CreditTransaction]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )


class CreditTransaction(Base, BaseIdModel, AuditMixin):
    """Credit 额度变动流水。"""

    __tablename__ = "credit_transactions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("credit_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的 Credit 账户ID",
    )
    amount: Mapped[int] = mapped_column(
        nullable=False,
        comment="变动数额(正为加，负为减)",
    )
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="变动来源: checkin/spend/expire/adjust",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="该笔额度到期时间，spend/expire/adjust 通常为 NULL，checkin 有值",
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="幂等键，例如对于签到使用 'checkin:user_id:yyyy-mm-dd' 保证一天只能签到一次",
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="附加元数据",
    )

    account: Mapped[CreditAccount] = relationship(back_populates="transactions")

    __table_args__ = (
        Index(
            "idx_credits_tx_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class UsageRecord(Base, BaseIdModel, AuditMixin):
    """LLM 调用实际 Token 用量与 Credits 折算消耗记录。"""

    __tablename__ = "usage_records"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的用户ID",
    )
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联的聊天消息ID",
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="调用的大模型名称",
    )
    input_tokens: Mapped[int] = mapped_column(
        default=0,
        server_default=text("0"),
        nullable=False,
        comment="输入 Token 数",
    )
    output_tokens: Mapped[int] = mapped_column(
        default=0,
        server_default=text("0"),
        nullable=False,
        comment="输出 Token 数",
    )
    credit_cost: Mapped[int] = mapped_column(
        default=0,
        server_default=text("0"),
        nullable=False,
        comment="本次调用折算扣减的 Credits 额度",
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="附加元数据",
    )

    user: Mapped[User] = relationship()
    chat_message: Mapped[ChatMessage | None] = relationship()

    __table_args__ = (
        Index(
            "idx_usage_records_chat_message_id_unique",
            "chat_message_id",
            unique=True,
            postgresql_where=text("chat_message_id IS NOT NULL"),
        ),
    )
