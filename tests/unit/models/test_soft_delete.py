"""Soft-delete filter and SoftDeleteMixin unit tests.

职责：验证全局 do_orm_execute 事件钩子、CRUDBase.get() 路径和 include_deleted 选项。
边界：使用 AsyncMock session，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from backend.models.orm.base import SoftDeleteMixin, _apply_soft_delete_filter
from backend.repositories.base import CRUDBase

# Helpers


def _make_execute_state(*, is_select: bool = True, include_deleted: bool = False):
    """Build a fake ExecuteState that mimics SQLAlchemy's do_orm_execute state."""
    stmt = MagicMock()
    stmt.options = MagicMock(return_value=stmt)

    state = MagicMock()
    state.is_select = is_select
    state.statement = stmt
    state.execution_options = (
        {"include_deleted": include_deleted} if include_deleted else {}
    )
    return state


# Tests: do_orm_execute event hook


async def test_soft_delete_filter_applies_to_select_statements() -> None:
    state = _make_execute_state(is_select=True, include_deleted=False)

    _apply_soft_delete_filter(state)

    state.statement.options.assert_called_once()
    call_args = state.statement.options.call_args
    assert call_args is not None


async def test_soft_delete_filter_skips_non_select_statements() -> None:
    state = _make_execute_state(is_select=False, include_deleted=False)

    _apply_soft_delete_filter(state)

    state.statement.options.assert_not_called()


async def test_soft_delete_filter_skips_when_include_deleted_is_true() -> None:
    state = _make_execute_state(is_select=True, include_deleted=True)

    _apply_soft_delete_filter(state)

    state.statement.options.assert_not_called()


# Tests: CRUDBase.get() uses select (not session.get)


async def test_crud_base_get_uses_select_not_session_get() -> None:
    from backend.models.orm.chat import ChatSession

    session = AsyncMock()
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=result_proxy)

    crud = CRUDBase(ChatSession, session)
    await crud.get(uuid.uuid4())

    session.execute.assert_awaited_once()
    session.get.assert_not_called()


# Tests: is_deleted property


def test_is_deleted_returns_true_when_deleted_at_is_set() -> None:
    from datetime import UTC, datetime

    class _Obj(SoftDeleteMixin):
        def __init__(self, deleted_at):
            self.deleted_at = deleted_at

    record = _Obj(deleted_at=datetime.now(UTC))
    assert record.is_deleted is True


def test_is_deleted_returns_false_when_deleted_at_is_none() -> None:
    class _Obj(SoftDeleteMixin):
        def __init__(self):
            self.deleted_at = None

    record = _Obj()
    assert record.is_deleted is False
