"""Storage column type migration contract tests.

职责：验证 knowledge_files 路径列的 revision 链、双向类型转换和 downgrade 防截断保护；
边界：动态加载 migration 并 mock Alembic op，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import sqlalchemy as sa

MIGRATION_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/2026_07_17_0700-7e4a9d2c1b60_migrate_storage_paths_to_text.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "storage_column_type_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_storage_column_migration_extends_current_head() -> None:
    migration = _load_migration()

    assert migration.revision == "7e4a9d2c1b60"
    assert migration.down_revision == "91a39c0c190c"


def test_upgrade_changes_both_storage_paths_to_text() -> None:
    migration = _load_migration()

    with patch.object(migration.op, "alter_column") as alter_column:
        migration.upgrade()

    assert [item.args[:2] for item in alter_column.call_args_list] == [
        ("knowledge_files", "file_path"),
        ("knowledge_files", "storage_key"),
    ]
    for item, nullable in zip(
        alter_column.call_args_list,
        (False, True),
        strict=True,
    ):
        assert type(item.kwargs["existing_type"]) is sa.String
        assert item.kwargs["existing_type"].length == 1024
        assert type(item.kwargs["type_"]) is sa.Text
        assert item.kwargs["existing_nullable"] is nullable


def test_downgrade_guards_length_before_restoring_varchar() -> None:
    migration = _load_migration()

    with (
        patch.object(migration.op, "execute") as execute,
        patch.object(migration.op, "alter_column") as alter_column,
    ):
        migration.downgrade()

    guard_sql = str(execute.call_args.args[0])
    assert "char_length(file_path) > 1024" in guard_sql
    assert "char_length(storage_key) > 1024" in guard_sql
    assert [item.args[1] for item in alter_column.call_args_list] == [
        "storage_key",
        "file_path",
    ]
    for item, nullable in zip(
        alter_column.call_args_list,
        (True, False),
        strict=True,
    ):
        assert type(item.kwargs["existing_type"]) is sa.Text
        assert type(item.kwargs["type_"]) is sa.String
        assert item.kwargs["type_"].length == 1024
        assert item.kwargs["existing_nullable"] is nullable
