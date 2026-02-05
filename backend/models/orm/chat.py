import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.orm.base import AuditMixin, Base, BaseIdModel


class ChatSession(Base, BaseIdModel, AuditMixin):
    """会话表：作为逻辑组和配置容器"""

    __tablename__ = "chat_sessions"

    title: Mapped[str] = mapped_column(String(255), default="新对话")
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kb_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("knowledge_bases.id"))

    # 扩展配置：如温度、模型选择
    model_config: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class MessageStatus(StrEnum):
    THINKING = "thinking"
    STREAMING = "streaming"
    SUCCESS = "success"
    FAILED = "failed"


class ChatMessage(Base, BaseIdModel, AuditMixin):
    """消息表：每一轮对话都会新增记录"""

    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user, assistant, system
    content: Mapped[str] = mapped_column(Text)

    # 状态控制
    status: Mapped[MessageStatus] = mapped_column(
        String(20), default=MessageStatus.THINKING
    )

    # RAG 溯源关键字段
    # 存储检索到的 Chunk ID 和相似度，用于前端展示“参考文献”
    search_context: Mapped[dict | None] = mapped_column(
        JSONB, comment="存储 RAG 检索到的原始分块信息"
    )

    # 性能审计
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)  # 记录模型响应耗时
    # 核心索引：确保按会话查询消息时，顺序是直接从索引读取的，无需内存排序
    __table_args__ = (Index("idx_msgs_session_created", "session_id", "created_at"),)
