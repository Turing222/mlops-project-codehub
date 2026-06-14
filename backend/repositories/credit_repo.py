"""Credit repository.

职责：定义 Credits 账户、变动流水、以及 LLM 使用账单的具体数据库读写方法。
边界：只执行数据库 CRUD 操作，不进行高级业务规则校验，与 Service 保持职责隔离。
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.credits import CreditAccount, CreditTransaction, UsageRecord


class CreditRepository:
    """Credits 仓库类，实现 CreditRepositoryProtocol 接口。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_account(self, user_id: uuid.UUID) -> CreditAccount | None:
        stmt = select(CreditAccount).where(CreditAccount.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_account_with_lock(self, user_id: uuid.UUID) -> CreditAccount | None:
        """使用 SELECT FOR UPDATE 悲观锁读取账户，避免高并发下扣费产生超支/覆盖问题。"""
        stmt = (
            select(CreditAccount)
            .where(CreditAccount.user_id == user_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_account_by_id_with_lock(
        self, account_id: uuid.UUID
    ) -> CreditAccount | None:
        """通过 account_id 使用 SELECT FOR UPDATE 悲观锁读取账户。"""
        stmt = (
            select(CreditAccount)
            .where(CreditAccount.id == account_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_account(self, user_id: uuid.UUID) -> CreditAccount:
        account = CreditAccount(user_id=user_id, balance=0)
        self.session.add(account)
        await self.session.flush()
        await self.session.refresh(account, attribute_names=["balance"])
        return account

    async def update_account_balance(self, account_id: uuid.UUID, balance: int) -> None:
        stmt = (
            update(CreditAccount)
            .where(CreditAccount.id == account_id)
            .values(balance=balance)
        )
        await self.session.execute(stmt)

    async def try_decrement_balance(self, account_id: uuid.UUID, cost: int) -> bool:
        """原子条件 UPDATE：仅当余额充足时扣减，单条 SQL 避免超支。"""
        stmt = (
            update(CreditAccount)
            .where(
                CreditAccount.id == account_id,
                CreditAccount.balance >= cost,
            )
            .values(balance=CreditAccount.balance - cost)
            .returning(CreditAccount.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def add_transaction(
        self,
        *,
        account_id: uuid.UUID,
        amount: int,
        source: str,
        expires_at: datetime.datetime | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CreditTransaction:
        tx = CreditTransaction(
            account_id=account_id,
            amount=amount,
            source=source,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            metadata_=metadata,
        )
        self.session.add(tx)
        await self.session.flush()
        await self.session.refresh(
            tx, attribute_names=["amount", "source", "expires_at"]
        )
        return tx

    async def get_transaction_by_idempotency_key(
        self, idempotency_key: str
    ) -> CreditTransaction | None:
        stmt = select(CreditTransaction).where(
            CreditTransaction.idempotency_key == idempotency_key
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_usage_record(
        self,
        *,
        user_id: uuid.UUID,
        chat_message_id: uuid.UUID | None = None,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        credit_cost: int,
        metadata: dict[str, Any] | None = None,
    ) -> UsageRecord:
        ur = UsageRecord(
            user_id=user_id,
            chat_message_id=chat_message_id,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            credit_cost=credit_cost,
            metadata_=metadata,
        )
        self.session.add(ur)
        await self.session.flush()
        return ur

    async def get_usage_record_by_chat_message_id(
        self, chat_message_id: uuid.UUID
    ) -> UsageRecord | None:
        stmt = select(UsageRecord).where(UsageRecord.chat_message_id == chat_message_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_transactions(
        self,
        *,
        account_id: uuid.UUID,
        source: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[CreditTransaction]:
        stmt = (
            select(CreditTransaction)
            .where(CreditTransaction.account_id == account_id)
            .order_by(CreditTransaction.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if source is not None:
            stmt = stmt.where(CreditTransaction.source == source)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_transactions(
        self, account_id: uuid.UUID, source: str | None = None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.account_id == account_id)
        )
        if source is not None:
            stmt = stmt.where(CreditTransaction.source == source)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_expired_grants_sum(
        self, account_id: uuid.UUID, now: datetime.datetime
    ) -> int:
        """获取用户历史上所有已到期的 checkin 额度之和。"""
        stmt = select(func.sum(CreditTransaction.amount)).where(
            CreditTransaction.account_id == account_id,
            CreditTransaction.source == "checkin",
            CreditTransaction.expires_at <= now,
        )
        result = await self.session.execute(stmt)
        val = result.scalar()
        return int(val) if val is not None else 0

    async def get_already_expired_sum(self, account_id: uuid.UUID) -> int:
        """获取用户历史上所有已经退款/冲正过期的额度之和（返回绝对值）。"""
        stmt = select(func.sum(CreditTransaction.amount)).where(
            CreditTransaction.account_id == account_id,
            CreditTransaction.source == "expire",
        )
        result = await self.session.execute(stmt)
        val = result.scalar()
        return abs(int(val)) if val is not None else 0

    async def get_spent_sum(self, account_id: uuid.UUID) -> int:
        """获取用户历史上所有模型调用消费的额度之和（返回绝对值）。"""
        stmt = select(func.sum(CreditTransaction.amount)).where(
            CreditTransaction.account_id == account_id,
            CreditTransaction.source == "spend",
        )
        result = await self.session.execute(stmt)
        val = result.scalar()
        return abs(int(val)) if val is not None else 0

    async def get_protected_positive_sum(
        self, account_id: uuid.UUID, now: datetime.datetime
    ) -> int:
        """获取不应由过期任务扣减的正向额度之和。"""
        stmt = select(func.sum(CreditTransaction.amount)).where(
            CreditTransaction.account_id == account_id,
            CreditTransaction.amount > 0,
            or_(
                CreditTransaction.source != "checkin",
                CreditTransaction.expires_at.is_(None),
                CreditTransaction.expires_at > now,
            ),
        )
        result = await self.session.execute(stmt)
        val = result.scalar()
        return int(val) if val is not None else 0

    async def try_increment_balance(self, account_id: uuid.UUID, amount: int) -> bool:
        """原子条件 UPDATE：余额增加指定额度。"""
        stmt = (
            update(CreditAccount)
            .where(CreditAccount.id == account_id)
            .values(balance=CreditAccount.balance + amount)
            .returning(CreditAccount.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_accounts_needing_expiration(
        self,
        now: datetime.datetime,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> Sequence[uuid.UUID]:
        """获取包含已过期且未处理 checkin 赠送的所有 CreditAccount 账户 ID。"""
        stmt = (
            select(CreditTransaction.account_id)
            .where(
                CreditTransaction.source == "checkin",
                CreditTransaction.expires_at <= now,
            )
            .distinct()
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
