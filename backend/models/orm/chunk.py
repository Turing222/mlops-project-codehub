import uuid
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.orm.base import Base, BaseIdModel


class ChunkSourceType(StrEnum):
    FILE = "file"
    CHAT_MESSAGE = "chat_message"


class DocumentChunk(Base, BaseIdModel):
    """RAG 切片表（支持知识库文件 & 历史对话等多态来源）"""
    __tablename__ = "document_chunks"

    # 区分来源
    source_type: Mapped[ChunkSourceType] = mapped_column(String(20), index=True, server_default=ChunkSourceType.FILE)

    # 用多外键的方式保留 DB 外键约束 (且保证总有一个不为空)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("knowledge_files.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True)

    # 原始切片内容
    content: Mapped[str] = mapped_column(Text)
    # 预计算 token 数，优化 LLM 上下文选择
    token_count: Mapped[int] = mapped_column(Integer)
    # 序列号，用于拼接上下文
    chunk_index: Mapped[int] = mapped_column(Integer)
    # 元数据：存储如 {"page_label": "12", "header": "Chapter 1"} 或 {"session_id": "..."}
    meta_info: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    # 768 维降维向量
    embedding: Mapped[Vector] = mapped_column(Vector(768))

    __table_args__ = (
        Index(
            "hnsw_idx_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        CheckConstraint(
            "(file_id IS NOT NULL)::int + (message_id IS NOT NULL)::int = 1",
            name="ck_chunk_exactly_one_source",
        ),
    )

    file: Mapped["File | None"] = relationship(back_populates="chunks")
    # message 的反向关联会定义在 ChatMessage 里
    message: Mapped["ChatMessage | None"] = relationship(back_populates="chunks")
