"""Audit repository unit tests.

职责：验证 AuditRepository 的计数和分页查询行为；边界：使用 AsyncMock session，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.orm.access import AuditOutcome
from backend.repositories.audit_repo import AuditEventFilters, AuditRepository


@pytest.fixture
def repo_ctx() -> tuple[AuditRepository, AsyncMock]:
    session = AsyncMock()
    repo = AuditRepository(session=session)
    return repo, session


async def test_count_events_applies_filters_returns_count(
    repo_ctx: tuple[AuditRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    actor_user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    filters = AuditEventFilters(
        action="chat.query_sent",
        outcome=AuditOutcome.SUCCESS,
        request_id="req-1",
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
    )
    session.scalar.return_value = 7

    result = await repo.count_events(filters)

    assert result == 7
    stmt = session.scalar.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "audit_events.action" in sql
    assert "audit_events.outcome" in sql
    assert "audit_events.request_id" in sql
    assert "audit_events.actor_user_id" in sql
    assert "audit_events.workspace_id" in sql


async def test_count_events_returns_zero_when_scalar_is_none(
    repo_ctx: tuple[AuditRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    session.scalar.return_value = None

    result = await repo.count_events(AuditEventFilters())

    assert result == 0


async def test_list_events_orders_and_paginates_returns_filtered(
    repo_ctx: tuple[AuditRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    expected = [MagicMock(), MagicMock()]
    result_proxy = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = expected
    result_proxy.scalars.return_value = scalars_proxy
    session.execute.return_value = result_proxy

    result = await repo.list_events(
        filters=AuditEventFilters(action="chat.query_stream"),
        skip=10,
        limit=20,
    )

    assert result == expected
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "audit_events.action" in sql
    assert "ORDER BY audit_events.created_at DESC" in sql
    assert "LIMIT" in sql
    assert "OFFSET" in sql
