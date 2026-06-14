"""Repo analysis ORM models.

职责：保存 GitHub 仓库可信度初筛 run 和报告结果。
边界：不拉取 GitHub、不调用 LLM、不渲染报告。
"""

import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.orm.base import AuditMixin, Base, BaseIdModel


class RepoAnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RepoAnalysisRun(Base, BaseIdModel, AuditMixin):
    """一次仓库可信度初筛任务。"""

    __tablename__ = "repo_analysis_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="提交分析的用户ID",
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("task_jobs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
        comment="关联 TaskJob ID",
    )
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    repo: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[RepoAnalysisStatus] = mapped_column(
        String(20), nullable=False, index=True, default=RepoAnalysisStatus.PENDING
    )
    rubric_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default="readme-only-v1"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class RepoAnalysisResult(Base, BaseIdModel, AuditMixin):
    """仓库初筛结构化证据和报告。"""

    __tablename__ = "repo_analysis_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("repo_analysis_runs.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    subject: Mapped[dict] = mapped_column(JSONB, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    structured_report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    markdown_report: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(40), nullable=False)
