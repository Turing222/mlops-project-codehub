import uuid
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.orm.base import AuditMixin, Base, BaseIdModel


class FileStatus(StrEnum):
    UPLOADED = "uploaded"  # 已上传，待解析
    PARSING = "parsing"  # 正在提取文本（OCR/PDF Parsing）
    CHUNKING = "chunking"  # 正在切片与向量化
    READY = "ready"  # 准备就绪
    FAILED = "failed"  # 处理失败


class KnowledgeBase(Base, BaseIdModel, AuditMixin):
    """知识库：文件的逻辑集合"""

    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )

    # 关联
    files: Mapped[list["File"]] = relationship(back_populates="kb")


class File(Base, BaseIdModel, AuditMixin):
    """
    修正后的文件表
    """

    __tablename__ = "files"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # 物理路径或 S3 Key
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[FileStatus] = mapped_column(String(20), default=FileStatus.UPLOADED)

    kb: Mapped["KnowledgeBase"] = relationship(back_populates="files")
    chunks: Mapped[list["FileChunk"]] = relationship(back_populates="file")


class FileChunk(Base, BaseIdModel):
    __tablename__ = "file_chunks"

    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    # 原始切片
    content: Mapped[str] = mapped_column(Text)
    # 预计算 token 数，优化 LLM 上下文选择
    token_count: Mapped[int] = mapped_column(Integer)
    # 序列号，用于拼接上下文
    chunk_index: Mapped[int] = mapped_column(Integer)
    # 元数据：存储如 {"page_label": "12", "header": "Chapter 1"}
    meta_info: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    # 向量字段依然可以这样组合
    embedding: Mapped[Vector] = mapped_column(Vector(768))
    __table_args__ = (
        Index(
            "hnsw_idx_file_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    file: Mapped["File"] = relationship(back_populates="chunks")
