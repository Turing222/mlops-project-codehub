from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.orm.base import AuditMixin, Base, BaseIdModel

if TYPE_CHECKING:
    from backend.models.orm.chunk import DocumentChunk
    from backend.models.orm.user import User


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
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # 关联
    user: Mapped[User] = relationship(back_populates="knowledge_bases")
    files: Mapped[list[File]] = relationship(
        back_populates="kb",
        cascade="all, delete-orphan",
    )


class File(Base, BaseIdModel, AuditMixin):
    """
    文件表（依附于知识库）
    """

    __tablename__ = "knowledge_files"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # 物理路径或 S3 Key
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[FileStatus] = mapped_column(String(20), default=FileStatus.UPLOADED)

    kb: Mapped[KnowledgeBase] = relationship(back_populates="files")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
    )
