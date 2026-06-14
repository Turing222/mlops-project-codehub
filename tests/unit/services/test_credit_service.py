"""CreditService unit tests.

职责：验证 Credits 账户只读查询、签到并发恢复和模型扣费幂等性；
边界：使用 mock repository，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from backend.core.exceptions import AppException
from backend.services.credit_service import CreditService

pytestmark = pytest.mark.asyncio


def make_account(*, balance: int = 1000) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), balance=balance)


def make_user(*, max_tokens: int = 100000, used_tokens: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), max_tokens=max_tokens, used_tokens=used_tokens
    )


def make_uow() -> SimpleNamespace:
    credit_repo = AsyncMock()
    credit_repo.get_account.return_value = None
    credit_repo.get_account_with_lock.return_value = None
    credit_repo.get_transaction_by_idempotency_key.return_value = None
    credit_repo.get_usage_record_by_chat_message_id.return_value = None
    credit_repo.list_transactions.return_value = []
    credit_repo.count_transactions.return_value = 0
    credit_repo.list_accounts_needing_expiration.return_value = []
    credit_repo.get_spent_sum.return_value = 0
    credit_repo.get_already_expired_sum.return_value = 0
    credit_repo.get_expired_grants_sum.return_value = 0
    credit_repo.get_protected_positive_sum.return_value = 0

    user_repo = AsyncMock()
    user_repo.get_with_lock.return_value = make_user()
    user_repo.increment_used_tokens = AsyncMock()
    user_repo.try_increment_used_tokens_with_limit = AsyncMock(return_value=True)

    @asynccontextmanager
    async def _noop_savepoint():
        yield uow

    uow = SimpleNamespace(
        credit_repo=credit_repo,
        user_repo=user_repo,
        rollback=AsyncMock(),
        savepoint=_noop_savepoint,
    )
    return uow


async def test_get_account_does_not_create_when_missing() -> None:
    uow = make_uow()
    service = CreditService(uow)

    result = await service.get_account(uuid.uuid4())

    assert result is None
    uow.credit_repo.create_account.assert_not_awaited()


async def test_list_user_transactions_returns_empty_when_account_missing() -> None:
    uow = make_uow()
    service = CreditService(uow)

    transactions, total = await service.list_user_transactions(
        user_id=uuid.uuid4(),
        skip=0,
        limit=20,
    )

    assert transactions == []
    assert total == 0
    uow.credit_repo.list_transactions.assert_not_awaited()
    uow.credit_repo.count_transactions.assert_not_awaited()


async def test_ensure_sufficient_balance_rejects_empty_balance() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=0)
    uow = make_uow()
    uow.user_repo.get_with_lock.return_value = make_user(max_tokens=0, used_tokens=0)
    uow.credit_repo.get_account_with_lock.return_value = account
    service = CreditService(uow)

    with pytest.raises(AppException) as exc_info:
        await service.ensure_sufficient_balance(user_id)

    assert exc_info.value.code == "CREDIT_QUOTA_EXCEEDED"
    assert exc_info.value.details == {"balance": 0, "estimated_cost": 10}
    uow.credit_repo.create_account.assert_not_awaited()


async def test_ensure_sufficient_balance_uses_savepoint_not_rollback() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.side_effect = [None, account]
    uow.credit_repo.create_account.side_effect = IntegrityError("insert", {}, None)
    service = CreditService(uow)

    result = await service.ensure_sufficient_balance(user_id)

    assert result is account
    uow.rollback.assert_not_awaited()
    assert uow.credit_repo.get_account_with_lock.await_count == 2


async def test_ensure_sufficient_balance_rejects_balance_below_estimated_cost() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=3)
    uow = make_uow()
    uow.user_repo.get_with_lock.return_value = make_user(max_tokens=0, used_tokens=0)
    uow.credit_repo.get_account_with_lock.return_value = account
    service = CreditService(uow)

    with pytest.raises(AppException) as exc_info:
        await service.ensure_sufficient_balance(user_id, estimated_cost=5)

    assert exc_info.value.code == "CREDIT_QUOTA_EXCEEDED"
    assert exc_info.value.details == {"balance": 3, "estimated_cost": 5}


async def test_ensure_sufficient_balance_recovers_from_concurrent_account_create() -> (
    None
):
    user_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.side_effect = [None, account]
    uow.credit_repo.create_account.side_effect = IntegrityError("insert", {}, None)
    service = CreditService(uow)

    result = await service.ensure_sufficient_balance(user_id)

    assert result is account
    uow.rollback.assert_not_awaited()
    assert uow.credit_repo.get_account_with_lock.await_count == 2


async def test_daily_checkin_recovers_from_concurrent_account_create() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=0)
    transaction = SimpleNamespace(id=uuid.uuid4(), amount=100)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.side_effect = [None, account]
    uow.credit_repo.create_account.side_effect = IntegrityError("insert", {}, None)
    uow.credit_repo.add_transaction.return_value = transaction

    service = CreditService(uow)

    result_account, result_transaction = await service.daily_checkin(user_id)

    assert result_account is account
    assert result_transaction is transaction
    assert account.balance == 100
    uow.rollback.assert_not_awaited()
    uow.credit_repo.try_increment_balance.assert_awaited_once_with(account.id, 100)


async def test_daily_checkin_rejects_duplicate_checkin() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    uow.credit_repo.get_transaction_by_idempotency_key.return_value = SimpleNamespace(
        id=uuid.uuid4()
    )

    service = CreditService(uow)

    with pytest.raises(AppException) as exc_info:
        await service.daily_checkin(user_id)

    assert exc_info.value.code == "ALREADY_CHECKED_IN"
    uow.credit_repo.add_transaction.assert_not_awaited()


async def test_spend_for_model_usage_is_idempotent_for_same_message() -> None:
    user_id = uuid.uuid4()
    chat_message_id = uuid.uuid4()
    usage_record = SimpleNamespace(id=uuid.uuid4())
    transaction = SimpleNamespace(id=uuid.uuid4())
    uow = make_uow()
    uow.credit_repo.get_transaction_by_idempotency_key.return_value = transaction
    uow.credit_repo.get_usage_record_by_chat_message_id.return_value = usage_record

    service = CreditService(uow)

    result_usage_record, result_transaction = await service.spend_for_model_usage(
        user_id=user_id,
        tokens_input=10,
        tokens_output=5,
        model_name="default",
        chat_message_id=chat_message_id,
    )

    assert result_usage_record is usage_record
    assert result_transaction is transaction
    uow.credit_repo.try_decrement_balance.assert_not_awaited()
    uow.credit_repo.create_usage_record.assert_not_awaited()
    uow.credit_repo.add_transaction.assert_not_awaited()


async def test_expire_credits_does_not_charge_future_balance_for_spent_grants() -> None:
    account_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.list_accounts_needing_expiration.side_effect = [[account_id], []]
    uow.credit_repo.get_account_by_id_with_lock.return_value = account
    uow.credit_repo.get_expired_grants_sum.return_value = 100
    uow.credit_repo.get_spent_sum.return_value = 100

    service = CreditService(uow)

    expired_count = await service.expire_credits()

    assert expired_count == 0
    assert account.balance == 100
    uow.credit_repo.update_account_balance.assert_not_awaited()
    uow.credit_repo.add_transaction.assert_not_awaited()


async def test_expire_credits_charges_only_unspent_expired_grants() -> None:
    account_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.list_accounts_needing_expiration.side_effect = [[account_id], []]
    uow.credit_repo.get_account_by_id_with_lock.return_value = account
    uow.credit_repo.get_expired_grants_sum.return_value = 100
    uow.credit_repo.get_spent_sum.return_value = 40
    uow.credit_repo.add_transaction.return_value = SimpleNamespace(id=uuid.uuid4())

    service = CreditService(uow)

    expired_count = await service.expire_credits()

    assert expired_count == 1
    # ORM object is NOT mutated; new_balance is computed locally.
    assert account.balance == 100
    uow.credit_repo.try_decrement_balance.assert_awaited_once_with(account.id, 60)
    uow.credit_repo.add_transaction.assert_awaited_once()
    assert uow.credit_repo.add_transaction.await_args.kwargs["amount"] == -60
    assert (
        uow.credit_repo.add_transaction.await_args.kwargs["metadata"]["spent_sum"] == 40
    )


async def test_expire_credits_protects_non_expiring_positive_balance() -> None:
    account_id = uuid.uuid4()
    account = make_account(balance=300)
    uow = make_uow()
    uow.credit_repo.list_accounts_needing_expiration.side_effect = [[account_id], []]
    uow.credit_repo.get_account_by_id_with_lock.return_value = account
    uow.credit_repo.get_expired_grants_sum.return_value = 300
    uow.credit_repo.get_spent_sum.return_value = 0
    uow.credit_repo.get_protected_positive_sum.return_value = 200
    uow.credit_repo.add_transaction.return_value = SimpleNamespace(id=uuid.uuid4())

    service = CreditService(uow)

    expired_count = await service.expire_credits()

    assert expired_count == 1
    uow.credit_repo.try_decrement_balance.assert_awaited_once_with(account.id, 100)
    assert uow.credit_repo.add_transaction.await_args.kwargs["amount"] == -100
    assert (
        uow.credit_repo.add_transaction.await_args.kwargs["metadata"][
            "protected_positive_sum"
        ]
        == 200
    )


async def test_spend_sufficient_credits() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=100)
    user = make_user(max_tokens=100000, used_tokens=0)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    uow.user_repo.get_with_lock.return_value = user
    uow.credit_repo.try_decrement_balance.return_value = True
    uow.credit_repo.create_usage_record.return_value = SimpleNamespace(
        id=uuid.uuid4(), credit_cost=10
    )
    uow.credit_repo.add_transaction.return_value = SimpleNamespace(id=uuid.uuid4())

    service = CreditService(uow)

    # Cost calculation: 10000 input + 0 output = 10 credits
    ur, tx = await service.spend_for_model_usage(
        user_id=user_id,
        tokens_input=10000,
        tokens_output=0,
        model_name="default",
    )

    uow.credit_repo.try_decrement_balance.assert_awaited_once_with(account.id, 10)
    uow.user_repo.increment_used_tokens.assert_not_awaited()


async def test_spend_partial_credits() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=4)
    user = make_user(max_tokens=100000, used_tokens=0)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    uow.user_repo.get_with_lock.return_value = user
    uow.credit_repo.try_decrement_balance.return_value = True
    uow.credit_repo.create_usage_record.return_value = SimpleNamespace(
        id=uuid.uuid4(), credit_cost=4
    )
    uow.credit_repo.add_transaction.return_value = SimpleNamespace(id=uuid.uuid4())

    service = CreditService(uow)

    # Cost calculation: 10000 input + 0 output = 10 credits.
    # User only has 4 credits, so credits_to_deduct = 4.
    # total_token_value = ceil(10000/1000 * 100) = 1000
    # token_value_covered_by_credits = 4 * 100 = 400
    # tokens_to_deduct = 1000 - 400 = 600
    ur, tx = await service.spend_for_model_usage(
        user_id=user_id,
        tokens_input=10000,
        tokens_output=0,
        model_name="default",
    )

    uow.credit_repo.try_decrement_balance.assert_awaited_once_with(account.id, 4)
    uow.user_repo.try_increment_used_tokens_with_limit.assert_awaited_once_with(
        user_id, 600
    )


async def test_spend_partial_credits_no_over_deduction_for_fractional_cost() -> None:
    """Small token counts should not over-deduct via double ceiling.

    Before the fix: raw_cost = ceil(0.002) = 1, then unpaid=1,
    tokens_to_deduct = ceil(1 * 100) = 100 → way over actual value of ~0.2 tokens.
    After the fix: total_token_value = ceil(0.2) = 1, credits cover 0,
    tokens_to_deduct = 1 - 0 = 1.
    """
    user_id = uuid.uuid4()
    account = make_account(balance=0)
    user = make_user(max_tokens=100000, used_tokens=0)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    uow.user_repo.get_with_lock.return_value = user
    uow.credit_repo.create_usage_record.return_value = SimpleNamespace(
        id=uuid.uuid4(), credit_cost=0
    )
    uow.credit_repo.add_transaction.return_value = SimpleNamespace(id=uuid.uuid4())

    service = CreditService(uow)

    ur, tx = await service.spend_for_model_usage(
        user_id=user_id,
        tokens_input=1,
        tokens_output=1,
        model_name="default",
    )

    # total_token_value = ceil((1*1 + 1*1) * 100 / 1000) = ceil(0.2) = 1
    # credits_to_deduct = 0, tokens_to_deduct = 1
    uow.credit_repo.try_decrement_balance.assert_not_awaited()
    uow.user_repo.try_increment_used_tokens_with_limit.assert_awaited_once_with(
        user_id, 1
    )


async def test_spend_zero_credits() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=0)
    user = make_user(max_tokens=100000, used_tokens=0)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    uow.user_repo.get_with_lock.return_value = user
    uow.credit_repo.create_usage_record.return_value = SimpleNamespace(
        id=uuid.uuid4(), credit_cost=0
    )
    uow.credit_repo.add_transaction.return_value = SimpleNamespace(id=uuid.uuid4())

    service = CreditService(uow)

    # Cost calculation: 10000 input + 0 output = 10 credits.
    # User has 0 credits, so credits_to_deduct = 0.
    # total_token_value = ceil(10000/1000 * 100) = 1000
    # tokens_to_deduct = 1000 - 0 = 1000
    ur, tx = await service.spend_for_model_usage(
        user_id=user_id,
        tokens_input=10000,
        tokens_output=0,
        model_name="default",
    )

    uow.credit_repo.try_decrement_balance.assert_not_awaited()
    uow.user_repo.try_increment_used_tokens_with_limit.assert_awaited_once_with(
        user_id, 1000
    )


async def test_spend_rejects_when_token_quota_is_insufficient() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=0)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    uow.user_repo.get_with_lock.return_value = make_user(
        max_tokens=1000, used_tokens=500
    )
    uow.user_repo.try_increment_used_tokens_with_limit.return_value = False

    service = CreditService(uow)

    with pytest.raises(AppException) as exc_info:
        await service.spend_for_model_usage(
            user_id=user_id,
            tokens_input=10000,
            tokens_output=0,
            model_name="default",
        )

    assert exc_info.value.code == "CREDIT_QUOTA_EXCEEDED"
    uow.credit_repo.create_usage_record.assert_not_awaited()


async def test_precheck_mixed_balance_pass() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=5)  # 500 tokens equivalent
    user = make_user(max_tokens=1000, used_tokens=500)  # 500 tokens remaining
    # Total capability = 500 + 500 = 1000 tokens.
    # Estimated cost = 10 credits = 1000 tokens.
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    uow.user_repo.get_with_lock.return_value = user

    service = CreditService(uow)

    # This should not raise, total capability is exactly 1000 tokens.
    result = await service.ensure_sufficient_balance(user_id, estimated_cost=10)
    assert result is account


async def test_precheck_mixed_balance_fail() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=5)  # 500 tokens equivalent
    user = make_user(max_tokens=1000, used_tokens=501)  # 499 tokens remaining
    # Total capability = 500 + 499 = 999 tokens.
    # Estimated cost = 10 credits = 1000 tokens.
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    uow.user_repo.get_with_lock.return_value = user

    service = CreditService(uow)

    with pytest.raises(AppException) as exc_info:
        await service.ensure_sufficient_balance(user_id, estimated_cost=10)

    assert exc_info.value.code == "CREDIT_QUOTA_EXCEEDED"
