from enum import StrEnum

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.orm.base import AuditMixin, Base, BaseIdModel


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskJob(Base, BaseIdModel, AuditMixin):
    __tablename__ = "task_jobs"

    action_type: Mapped[str] = mapped_column(
        String(50)
    )  # "KB_INGESTION" 或 "RAG_QUERY"
    status: Mapped[TaskStatus] = mapped_column(String(20))
    progress: Mapped[int] = mapped_column(default=0)  # 0-100%
    payload: Mapped[dict] = mapped_column(JSONB)  # 记录任务参数（如 kb_id, query_text）
    error_log: Mapped[str | None] = mapped_column(Text)
