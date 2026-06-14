"""Credits API unit tests.

职责：验证 Credits endpoint 的 service 调用与空账户响应；边界：直接调用 endpoint 函数，
不启动 FastAPI app 或真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.v1.endpoint import credit_api
from backend.core.exceptions import AppException

pytestmark = pytest.mark.asyncio


class DummyReadContext:
    async def __aenter__(self) -> DummyReadContext:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class DummyWriteContext:
    def __init__(self) -> None:
        self.commit = AsyncMock()

    async def __aenter__(self) -> DummyWriteContext:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def make_user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def make_credit_service() -> SimpleNamespace:
    service = SimpleNamespace(
        get_account=AsyncMock(return_value=None),
        is_checked_in_today=AsyncMock(return_value=False),
        list_user_transactions=AsyncMock(return_value=([], 0)),
        daily_checkin=AsyncMock(),
    )
    service.read = lambda: DummyReadContext()
    service.write = lambda: DummyWriteContext()
    return service


async def test_get_my_credits_returns_zero_view_without_creating_account() -> None:
    user = make_user()
    credit_service = make_credit_service()

    result = await credit_api.get_my_credits(
        current_user=user,
        credit_service=credit_service,
    )

    assert result.id is None
    assert result.user_id == user.id
    assert result.balance == 0
    assert result.is_checked_in_today is False
    assert result.created_at is None
    assert result.updated_at is None
    credit_service.get_account.assert_awaited_once_with(user.id)
    credit_service.is_checked_in_today.assert_not_awaited()


async def test_list_my_transactions_returns_empty_for_missing_account() -> None:
    user = make_user()
    credit_service = make_credit_service()

    result = await credit_api.list_my_transactions(
        current_user=user,
        credit_service=credit_service,
        skip=0,
        limit=20,
    )

    assert result.items == []
    assert result.total == 0
    credit_service.list_user_transactions.assert_awaited_once_with(
        user_id=user.id,
        source=None,
        skip=0,
        limit=20,
    )


async def test_daily_checkin_returns_success_with_balance() -> None:
    user = make_user()
    account = SimpleNamespace(id=uuid.uuid4(), balance=200)
    expires_at = datetime(2026, 6, 1, tzinfo=UTC)
    tx = SimpleNamespace(id=uuid.uuid4(), amount=100, expires_at=expires_at)
    credit_service = make_credit_service()
    credit_service.daily_checkin.return_value = (account, tx)

    result = await credit_api.daily_checkin(
        current_user=user,
        credit_service=credit_service,
    )

    assert result.success is True
    assert result.balance == 200
    assert result.amount_earned == 100
    assert result.expires_at == expires_at
    credit_service.daily_checkin.assert_awaited_once_with(user.id)


async def test_daily_checkin_expires_at_fallback_when_none() -> None:
    user = make_user()
    account = SimpleNamespace(id=uuid.uuid4(), balance=100)
    tx = SimpleNamespace(id=uuid.uuid4(), amount=100, expires_at=None)
    credit_service = make_credit_service()
    credit_service.daily_checkin.return_value = (account, tx)

    result = await credit_api.daily_checkin(
        current_user=user,
        credit_service=credit_service,
    )

    assert result.success is True
    assert result.expires_at is not None
    # Fallback: expires_at should be roughly now (within 60s tolerance)
    delta = abs((result.expires_at - datetime.now(UTC)).total_seconds())
    assert delta < 60


async def test_daily_checkin_already_checked_in_raises() -> None:
    user = make_user()
    credit_service = make_credit_service()
    credit_service.daily_checkin.side_effect = AppException(
        code="ALREADY_CHECKED_IN",
        message="已签到",
    )

    with pytest.raises(AppException) as exc_info:
        await credit_api.daily_checkin(
            current_user=user,
            credit_service=credit_service,
        )

    assert exc_info.value.code == "ALREADY_CHECKED_IN"
