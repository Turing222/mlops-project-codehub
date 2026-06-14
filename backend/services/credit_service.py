"""Credit Service.

职责：处理 Credits 核心业务逻辑，包括每日签到、模型调用扣费折算、以及额度过期清理。
边界：不感知 HTTP 层或 API Router，通过 UnitOfWork 隔离数据操作。
"""

from __future__ import annotations

import datetime
import logging
import math
import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError

from backend.config.credit_settings import credit_settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import app_validation_error
from backend.models.orm.credits import CreditAccount, CreditTransaction, UsageRecord
from backend.services.base import BaseService

logger = logging.getLogger(__name__)


class CreditService(BaseService[AbstractUnitOfWork]):
    """Credits 积分与额度服务类。"""

    def __init__(self, uow: AbstractUnitOfWork) -> None:
        super().__init__(uow)

    async def is_checked_in_today(self, user_id: uuid.UUID) -> bool:
        """检查用户今日是否已签到。"""
        now = datetime.datetime.now(datetime.UTC)
        date_str = now.strftime("%Y-%m-%d")
        idempotency_key = f"checkin:{user_id}:{date_str}"
        existing_tx = await self.uow.credit_repo.get_transaction_by_idempotency_key(
            idempotency_key
        )
        return existing_tx is not None

    async def get_account(self, user_id: uuid.UUID) -> CreditAccount | None:
        """获取用户的 Credits 账户，不隐式创建。"""
        return await self.uow.credit_repo.get_account(user_id)

    async def _get_or_create_account_with_lock(
        self, user_id: uuid.UUID, *, lock: bool = True
    ) -> CreditAccount:
        """Get or create a CreditAccount, recovering from concurrent creates via savepoint."""
        get_fn = (
            self.uow.credit_repo.get_account_with_lock
            if lock
            else self.uow.credit_repo.get_account
        )
        account = await get_fn(user_id)
        if account:
            return account
        try:
            async with self.uow.savepoint():
                account = await self.uow.credit_repo.create_account(user_id)
                return account
        except IntegrityError:
            account = await get_fn(user_id)
            if not account:
                raise
            return account

    async def get_or_create_account(self, user_id: uuid.UUID) -> CreditAccount:
        """获取或创建用户的 Credits 账户。"""
        return await self._get_or_create_account_with_lock(user_id, lock=False)

    async def ensure_sufficient_balance(
        self, user_id: uuid.UUID, *, estimated_cost: int | None = None
    ) -> CreditAccount:
        """锁定用户和积分账户，并确认总额度可发起模型生成。"""
        # 1. 悲观锁依次读取 User 和 CreditAccount，避免并发竞态与死锁
        user = await self.uow.user_repo.get_with_lock(user_id)
        if not user:
            raise app_validation_error("用户不存在", code="USER_NOT_FOUND")

        account = await self._get_or_create_account_with_lock(user_id)

        # 2. 计算预估的积分和 Token 消耗
        cost_in_credits = (
            estimated_cost
            if estimated_cost is not None
            else credit_settings.CREDIT_MINIMUM_ESTIMATED_COST
        )

        # 3. 混合余额校验：
        # 积分余额可折算的 Token 数
        credits_in_tokens = account.balance * credit_settings.CREDIT_TO_TOKEN_RATIO
        # 用户账户剩余的 Token 额度
        remaining_tokens = max(0, user.max_tokens - user.used_tokens)

        # 本次请求所需的总 Token 预估
        required_tokens = cost_in_credits * credit_settings.CREDIT_TO_TOKEN_RATIO

        if remaining_tokens + credits_in_tokens < required_tokens:
            raise app_validation_error(
                "Credits 余额不足，请先签到获取额度",
                code="CREDIT_QUOTA_EXCEEDED",
                details={
                    "balance": account.balance,
                    "estimated_cost": cost_in_credits,
                },
            )

        return account

    async def list_user_transactions(
        self,
        *,
        user_id: uuid.UUID,
        source: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[CreditTransaction], int]:
        """分页获取用户 Credits 流水；账户不存在时返回空结果。"""
        account = await self.uow.credit_repo.get_account(user_id)
        if not account:
            return [], 0

        transactions = await self.uow.credit_repo.list_transactions(
            account_id=account.id,
            source=source,
            skip=skip,
            limit=limit,
        )
        total = await self.uow.credit_repo.count_transactions(account.id, source=source)
        return transactions, total

    async def daily_checkin(
        self, user_id: uuid.UUID
    ) -> tuple[CreditAccount, CreditTransaction]:
        """执行每日签到，增加赠送额度。

        采用以日期为维度的唯一幂等键，保证一天内只能签到成功一次。
        """
        # 1. 确保账户存在并加锁
        account = await self._get_or_create_account_with_lock(user_id)

        # 2. 生成基于当天 UTC 日期的幂等键
        now = datetime.datetime.now(datetime.UTC)
        date_str = now.strftime("%Y-%m-%d")
        idempotency_key = f"checkin:{user_id}:{date_str}"

        # 3. 幂等性校验
        existing_tx = await self.uow.credit_repo.get_transaction_by_idempotency_key(
            idempotency_key
        )
        if existing_tx:
            raise app_validation_error(
                "您今天已经签到过了，明天再来吧",
                code="ALREADY_CHECKED_IN",
            )

        # 4. 执行签到，计算有效期
        amount = credit_settings.CREDIT_DAILY_CHECKIN_AMOUNT
        valid_days = credit_settings.CREDIT_DAILY_CHECKIN_VALID_DAYS
        expires_at = now + datetime.timedelta(days=valid_days)

        # 5. 添加交易流水，更新余额（余额更新在 savepoint 内保证原子性）
        try:
            async with self.uow.savepoint():
                tx = await self.uow.credit_repo.add_transaction(
                    account_id=account.id,
                    amount=amount,
                    source="checkin",
                    expires_at=expires_at,
                    idempotency_key=idempotency_key,
                    metadata={"valid_days": valid_days},
                )
                await self.uow.credit_repo.try_increment_balance(account.id, amount)
        except IntegrityError as exc:
            raise app_validation_error(
                "您今天已经签到过了，明天再来吧",
                code="ALREADY_CHECKED_IN",
            ) from exc

        account.balance += amount

        logger.info(
            "User %s checked in successfully. Earned %d credits.",
            user_id,
            amount,
        )
        return account, tx

    async def spend_for_model_usage(
        self,
        *,
        user_id: uuid.UUID,
        tokens_input: int,
        tokens_output: int,
        model_name: str,
        chat_message_id: uuid.UUID | None = None,
    ) -> tuple[UsageRecord, CreditTransaction]:
        """根据大模型 Token 用量和折算费率扣除 Credits。优先扣积分，不足部分扣 Token。

        此方法在 write() UoW 上下文中调用；若 token 扣减失败（如余额不足触发异常），
        整个事务将回滚，不会产生部分写入。
        """
        # 1. 费率折算
        rates = credit_settings.CREDIT_MODEL_RATES.get(
            model_name
        ) or credit_settings.CREDIT_MODEL_RATES.get("default", {})
        input_rate = rates.get("input", 1.0)
        output_rate = rates.get("output", 1.0)

        raw_cost = (tokens_input * input_rate + tokens_output * output_rate) / 1000.0
        cost = math.ceil(raw_cost)
        spend_idempotency_key = (
            f"spend:{chat_message_id}" if chat_message_id is not None else None
        )

        if spend_idempotency_key is not None:
            existing_tx = await self.uow.credit_repo.get_transaction_by_idempotency_key(
                spend_idempotency_key
            )
            existing_usage_record = None
            if chat_message_id is not None:
                existing_usage_record = (
                    await self.uow.credit_repo.get_usage_record_by_chat_message_id(
                        chat_message_id
                    )
                )
            if existing_tx is not None and existing_usage_record is not None:
                return existing_usage_record, existing_tx
            if existing_usage_record is not None:
                # Recovery: balance was decremented by try_decrement_balance in
                # original attempt; only the transaction record was lost.
                account = await self._get_or_create_account_with_lock(user_id)
                try:
                    async with self.uow.savepoint():
                        tx = await self.uow.credit_repo.add_transaction(
                            account_id=account.id,
                            amount=-existing_usage_record.credit_cost,
                            source="spend",
                            idempotency_key=spend_idempotency_key,
                            metadata={"usage_record_id": str(existing_usage_record.id)},
                        )
                except IntegrityError:
                    tx = await self.uow.credit_repo.get_transaction_by_idempotency_key(
                        spend_idempotency_key
                    )
                    if tx is None:
                        raise
                return existing_usage_record, tx

        # 2. 锁定账户并校验余额
        user = await self.uow.user_repo.get_with_lock(user_id)
        if not user:
            raise app_validation_error("用户不存在", code="USER_NOT_FOUND")
        account = await self._get_or_create_account_with_lock(user_id)

        # 3. 混合抵扣算法：从原始未取整金额计算总 token 等价值，避免双重取整超扣
        total_token_value = math.ceil(
            (tokens_input * input_rate + tokens_output * output_rate)
            * credit_settings.CREDIT_TO_TOKEN_RATIO
            / 1000.0
        )

        if account.balance >= cost:
            # 情况 A: 积分充足，全额由积分抵扣
            credits_to_deduct = cost
            tokens_to_deduct = 0
        else:
            # 情况 B: 积分不足，积分扣空，剩余部分扣除 Token
            credits_to_deduct = account.balance
            token_value_covered_by_credits = int(
                credits_to_deduct * credit_settings.CREDIT_TO_TOKEN_RATIO
            )
            tokens_to_deduct = total_token_value - token_value_covered_by_credits
            if tokens_to_deduct < 0:
                tokens_to_deduct = 0

        # 4. 原子扣减积分
        if credits_to_deduct > 0:
            ok = await self.uow.credit_repo.try_decrement_balance(
                account.id, credits_to_deduct
            )
            if not ok:
                raise app_validation_error(
                    "您的 Credits 余额不足，请先签到获取额度",
                    code="INSUFFICIENT_CREDITS",
                )

        # 5. 原子扣减 Token 额度
        if tokens_to_deduct > 0:
            can_deduct_tokens = (
                await self.uow.user_repo.try_increment_used_tokens_with_limit(
                    user_id, tokens_to_deduct
                )
            )
            if not can_deduct_tokens:
                raise app_validation_error(
                    "Credits 余额不足，请先签到获取额度",
                    code="CREDIT_QUOTA_EXCEEDED",
                    details={
                        "balance": account.balance,
                        "estimated_cost": cost,
                    },
                )

        # 6. 写入详细消费记录与交易流水
        ur = await self.uow.credit_repo.create_usage_record(
            user_id=user_id,
            chat_message_id=chat_message_id,
            model_name=model_name,
            input_tokens=tokens_input,
            output_tokens=tokens_output,
            credit_cost=credits_to_deduct,
            metadata={
                "token_deduction": tokens_to_deduct,
                "credit_deduction": credits_to_deduct,
                "ratio_applied": credit_settings.CREDIT_TO_TOKEN_RATIO,
            },
        )

        tx = await self.uow.credit_repo.add_transaction(
            account_id=account.id,
            amount=-credits_to_deduct,
            source="spend",
            idempotency_key=spend_idempotency_key,
            metadata={
                "usage_record_id": str(ur.id),
                "token_deduction": tokens_to_deduct,
            },
        )

        logger.info(
            "User %s spent %d credits and %d tokens for model %s (input: %d, output: %d). Message ID: %s.",
            user_id,
            credits_to_deduct,
            tokens_to_deduct,
            model_name,
            tokens_input,
            tokens_output,
            chat_message_id,
        )
        return ur, tx

    async def expire_credits_for_account(
        self, account_id: uuid.UUID, now: datetime.datetime
    ) -> bool:
        """对单个账户执行过期额度清理（独立事务）。

        Returns:
            True 表示该账户有额度被过期清理。
        """
        # 1. 悲观锁读取当前账户
        account = await self.uow.credit_repo.get_account_by_id_with_lock(account_id)
        if not account:
            return False

        # 2. 汇总已过期授权与已标记过期的流水之差，计算出还需要扣减的差值
        expired_grants_sum = await self.uow.credit_repo.get_expired_grants_sum(
            account_id, now
        )
        already_expired_sum = await self.uow.credit_repo.get_already_expired_sum(
            account_id
        )
        spent_sum = await self.uow.credit_repo.get_spent_sum(account_id)
        protected_positive_sum = await self.uow.credit_repo.get_protected_positive_sum(
            account_id, now
        )

        pending_expire = expired_grants_sum - spent_sum - already_expired_sum
        if pending_expire <= 0:
            return False

        # 3. 保护非过期 / 非 checkin 正向额度，避免过期任务误扣长期余额。
        expirable_balance = max(0, account.balance - protected_positive_sum)
        to_expire = min(expirable_balance, pending_expire)
        if to_expire > 0:
            await self.uow.credit_repo.try_decrement_balance(account.id, to_expire)

            await self.uow.credit_repo.add_transaction(
                account_id=account.id,
                amount=-to_expire,
                source="expire",
                metadata={
                    "expired_grants_sum": expired_grants_sum,
                    "spent_sum": spent_sum,
                    "already_expired_sum": already_expired_sum,
                    "protected_positive_sum": protected_positive_sum,
                    "calculation_time": now.isoformat(),
                },
            )
            logger.info(
                "Account %s expired %d credits (expired grants: %d, spent: %d, already expired: %d).",
                account_id,
                to_expire,
                expired_grants_sum,
                spent_sum,
                already_expired_sum,
            )
            return True
        return False

    async def expire_credits(self) -> int:
        """执行过期的 Credit 额度清理（分页扫描 + 逐账户独立事务）。

        由后台 Cron 每日调用，找出所有已过期的 checkin 赠送，
        扣减剩余未被消费的部分，并生成类型为 expire 的反向流水冲正。
        """
        now = datetime.datetime.now(datetime.UTC)
        expired_count = 0
        batch_size = 200
        max_pages = 100_000

        for page_index in range(max_pages):
            offset = page_index * batch_size
            account_ids = await self.uow.credit_repo.list_accounts_needing_expiration(
                now, limit=batch_size, offset=offset
            )
            if not account_ids:
                break

            for account_id in account_ids:
                try:
                    async with self.uow.savepoint():
                        did_expire = await self.expire_credits_for_account(
                            account_id, now
                        )
                        if did_expire:
                            expired_count += 1
                except Exception:
                    logger.exception(
                        "Failed to expire credits for account %s, skipping.",
                        account_id,
                    )
        else:
            raise RuntimeError("credit expiration exceeded max_pages")

        return expired_count
