"""Chat generation recovery migration contract tests.

职责：验证 dispatch accounting revision、active row 回填和 ORM 约束；
边界：动态加载 migration 并 mock Alembic op，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from backend.models.orm.chat import ChatGenerationRequest

MIGRATION_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/2026_07_17_0915-8c1d7e4a9b20_add_chat_dispatch_attempts.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "chat_generation_recovery_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_dispatch_attempts_orm_contract_is_additive() -> None:
    table = ChatGenerationRequest.__table__

    column = table.columns["dispatch_attempts"]
    assert isinstance(column.type, sa.Integer)
    assert column.nullable is False
    assert str(column.server_default.arg) == "0"
    constraint_names = {constraint.name for constraint in table.constraints}
    assert (
        "ck_chat_generation_requests_dispatch_attempts_non_negative" in constraint_names
    )
    context_column = table.columns["dispatch_context"]
    assert isinstance(context_column.type, JSONB)
    assert context_column.nullable is True


def test_recovery_migration_extends_generation_request_head() -> None:
    migration = _load_migration()

    assert migration.revision == "8c1d7e4a9b20"
    assert migration.down_revision == "5f4c2a9d8e71"


def test_upgrade_adds_dispatch_count_and_backfills_active_rows() -> None:
    migration = _load_migration()

    with (
        patch.object(migration.op, "f", side_effect=lambda name: name),
        patch.object(migration.op, "add_column") as add_column,
        patch.object(migration.op, "execute") as execute,
        patch.object(migration.op, "create_check_constraint") as create_check,
    ):
        migration.upgrade()

    assert add_column.call_count == 2
    first_call, second_call = add_column.call_args_list
    assert first_call.args[0] == "chat_generation_requests"
    column = first_call.args[1]
    assert column.name == "dispatch_attempts"
    assert column.nullable is False
    assert str(column.server_default.arg) == "0"
    assert second_call.args[0] == "chat_generation_requests"
    context_column = second_call.args[1]
    assert context_column.name == "dispatch_context"
    assert isinstance(context_column.type, JSONB)
    assert context_column.nullable is True
    assert "WHERE task_id IS NOT NULL" in str(execute.call_args.args[0])
    assert create_check.call_args.args == (
        "ck_chat_generation_requests_dispatch_attempts_non_negative",
        "chat_generation_requests",
        "dispatch_attempts >= 0",
    )


def test_downgrade_removes_only_dispatch_accounting() -> None:
    migration = _load_migration()

    with (
        patch.object(migration.op, "f", side_effect=lambda name: name),
        patch.object(migration.op, "drop_constraint") as drop_constraint,
        patch.object(migration.op, "drop_column") as drop_column,
    ):
        migration.downgrade()

    assert drop_constraint.call_args.args[:2] == (
        "ck_chat_generation_requests_dispatch_attempts_non_negative",
        "chat_generation_requests",
    )
    assert drop_constraint.call_args.kwargs["type_"] == "check"
    assert [call.args for call in drop_column.call_args_list] == [
        ("chat_generation_requests", "dispatch_context"),
        ("chat_generation_requests", "dispatch_attempts"),
    ]
