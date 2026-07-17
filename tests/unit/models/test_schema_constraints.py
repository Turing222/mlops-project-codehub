"""ORM schema constraint and index contract tests.

职责：锁定关键 CHECK 约束、部分唯一索引与复合索引的 ORM 定义；边界：只读 __table__ 元数据，不连接数据库；副作用：无。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Text

from backend.models.orm.access import Workspace
from backend.models.orm.chat import ChatMessage, ChatSession
from backend.models.orm.credits import CreditAccount, CreditTransaction
from backend.models.orm.knowledge import File as KnowledgeFile
from backend.models.orm.task import TaskJob, TaskOutbox


def _index_by_name(model: type) -> dict[str, object]:
    return {index.name: index for index in model.__table__.indexes}


def test_credit_account_declares_balance_non_negative_check() -> None:
    check_names = {
        constraint.name
        for constraint in CreditAccount.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_credit_accounts_balance_non_negative" in check_names


def test_workspaces_slug_is_unique_only_among_active_rows() -> None:
    indexes = _index_by_name(Workspace)
    slug_index = indexes.get("uq_workspaces_slug_active")
    assert slug_index is not None
    assert slug_index.unique is True
    # 部分唯一索引必须带 deleted_at IS NULL 谓词，否则软删后无法复用 slug。
    assert slug_index.dialect_kwargs.get("postgresql_where") is not None
    # 旧的全局唯一索引已移除。
    assert "ix_workspaces_slug" not in indexes


def test_chat_sessions_has_user_updated_composite_index() -> None:
    index = _index_by_name(ChatSession).get("ix_chat_sessions_user_updated")
    assert index is not None
    assert [column.name for column in index.columns] == ["user_id", "updated_at"]


def test_knowledge_file_storage_paths_use_unbounded_text() -> None:
    table = KnowledgeFile.__table__

    assert isinstance(table.columns["file_path"].type, Text)
    assert table.columns["file_path"].nullable is False
    assert isinstance(table.columns["storage_key"].type, Text)
    assert table.columns["storage_key"].nullable is True


def test_current_chat_client_request_id_unique_index_is_global() -> None:
    """WS2 基线：Redis 按用户分域，但当前 DB 唯一索引不包含 owner。"""
    index = _index_by_name(ChatMessage).get("idx_msgs_client_req_id")

    assert index is not None
    assert index.unique is True
    assert [column.name for column in index.columns] == ["client_request_id"]
    assert index.dialect_kwargs.get("postgresql_where") is not None


def test_credit_transactions_has_account_created_composite_index() -> None:
    index = _index_by_name(CreditTransaction).get(
        "ix_credit_transactions_account_created"
    )
    assert index is not None
    assert [column.name for column in index.columns] == ["account_id", "created_at"]


def test_task_job_has_user_id_foreign_key_and_timing_columns() -> None:
    table = TaskJob.__table__
    assert {"user_id", "started_at", "finished_at"} <= set(table.columns.keys())

    foreign_keys = list(table.columns["user_id"].foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].column.table.name == "users"


def test_task_job_and_outbox_declare_durable_ingestion_state() -> None:
    columns = set(TaskJob.__table__.columns.keys())

    assert {
        "knowledge_file_id",
        "knowledge_base_id",
        "attempt_count",
        "heartbeat_at",
        "lease_expires_at",
    } <= columns
    assert "task_outbox" in TaskJob.metadata.tables

    outbox_columns = set(TaskOutbox.__table__.columns.keys())
    assert {
        "task_id",
        "event_type",
        "payload",
        "status",
        "attempt_count",
        "next_attempt_at",
        "lease_owner",
        "lease_expires_at",
        "published_at",
        "last_error",
    } <= outbox_columns
    assert "ix_task_outbox_claim" in _index_by_name(TaskOutbox)
