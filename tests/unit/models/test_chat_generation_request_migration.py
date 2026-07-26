"""Chat generation request ORM and migration contract tests.

职责：验证 durable request 的 revision 链、核心列、数据库约束与索引定义；
边界：动态加载 migration 并 mock Alembic op，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import sqlalchemy as sa

from backend.models.enums import ChatGenerationStatus
from backend.models.orm.chat import ChatGenerationRequest

MIGRATION_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/2026_07_17_0830-5f4c2a9d8e71_add_chat_generation_requests.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "chat_generation_request_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_generation_request_status_contract_is_frozen() -> None:
    assert [status.value for status in ChatGenerationStatus] == [
        "prepared",
        "queued",
        "running",
        "succeeded",
        "failed",
    ]


def test_generation_request_orm_exposes_identity_and_recovery_fields() -> None:
    table = ChatGenerationRequest.__table__

    assert set(table.columns.keys()) >= {
        "id",
        "user_id",
        "workspace_id",
        "session_id",
        "user_message_id",
        "assistant_message_id",
        "client_request_id",
        "task_id",
        "status",
        "attempt",
        "lease_token",
        "heartbeat_at",
        "lease_expires_at",
        "recovery_due_at",
        "retryable",
        "error_code",
        "finished_at",
    }
    constraint_names = {constraint.name for constraint in table.constraints}
    assert "uq_chat_generation_requests_user_client_request" in constraint_names
    assert "ck_chat_generation_requests_active_attempt_fence" in constraint_names
    assert "ck_chat_generation_requests_terminal_finished_at" in constraint_names
    assert "ck_chat_generation_requests_failed_error_code" in constraint_names
    index_names = {index.name for index in table.indexes}
    assert "uq_chat_generation_requests_assistant_message" in index_names
    assert "ix_chat_generation_requests_recovery_due" in index_names


def test_generation_request_migration_extends_storage_migration() -> None:
    migration = _load_migration()

    assert migration.revision == "5f4c2a9d8e71"
    assert migration.down_revision == "7e4a9d2c1b60"


def test_upgrade_creates_durable_request_constraints_and_indexes() -> None:
    migration = _load_migration()

    with (
        patch.object(migration.op, "f", side_effect=lambda name: name),
        patch.object(migration.op, "create_table") as create_table,
        patch.object(migration.op, "create_index") as create_index,
    ):
        migration.upgrade()

    assert create_table.call_args.args[0] == "chat_generation_requests"
    definitions = create_table.call_args.args[1:]
    columns = {
        definition.name: definition
        for definition in definitions
        if isinstance(definition, sa.Column)
    }
    assert columns["client_request_id"].nullable is False
    assert columns["attempt"].server_default is not None
    assert str(columns["attempt"].server_default.arg) == "1"
    assert columns["workspace_id"].nullable is True
    assert columns["recovery_due_at"].type.timezone is True

    unique_constraints = [
        definition
        for definition in definitions
        if isinstance(definition, sa.UniqueConstraint)
    ]
    assert unique_constraints[0]._pending_colargs == [  # noqa: SLF001
        "user_id",
        "client_request_id",
    ]
    checks = {
        definition.name: str(definition.sqltext)
        for definition in definitions
        if isinstance(definition, sa.CheckConstraint)
    }
    assert "attempt >= 1" in checks["ck_chat_generation_requests_attempt_positive"]
    assert (
        "length(btrim(lease_token)) > 0"
        in checks["ck_chat_generation_requests_active_attempt_fence"]
    )
    assert (
        "finished_at IS NOT NULL"
        in checks["ck_chat_generation_requests_terminal_finished_at"]
    )

    created_indexes = {call.args[0]: call for call in create_index.call_args_list}
    assert created_indexes["uq_chat_generation_requests_assistant_message"].kwargs[
        "unique"
    ]
    assert "recovery_due_at IS NOT NULL" in str(
        created_indexes["ix_chat_generation_requests_recovery_due"].kwargs[
            "postgresql_where"
        ]
    )


def test_downgrade_only_removes_additive_request_table() -> None:
    migration = _load_migration()

    with (
        patch.object(migration.op, "f", side_effect=lambda name: name),
        patch.object(migration.op, "drop_index") as drop_index,
        patch.object(migration.op, "drop_table") as drop_table,
    ):
        migration.downgrade()

    assert len(drop_index.call_args_list) == 6
    drop_table.assert_called_once_with("chat_generation_requests")
