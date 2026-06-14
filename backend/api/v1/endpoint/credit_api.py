"""Credits API Endpoint.

职责：提供 Credits 账户查询、签到和流水变动列表的 HTTP 接口。
边界：只处理 HTTP 入参校验、异常映射和 JSON 编解码，核心逻辑由 CreditService 执行。
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import get_credit_service, get_current_active_user
from backend.models.orm.user import User
from backend.models.schemas.credit_schema import (
    CheckinResponse,
    CreditAccountResponse,
    CreditTransactionResponse,
    CreditTransactionsListResponse,
)
from backend.services.credit_service import CreditService

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
CreditServiceDep = Annotated[CreditService, Depends(get_credit_service)]


@router.get("/me")
async def get_my_credits(
    current_user: CurrentUserDep,
    credit_service: CreditServiceDep,
) -> CreditAccountResponse:
    """获取当前用户的 Credits 账户信息，包括当前余额及今日是否已签到。"""
    async with credit_service.read():
        account = await credit_service.get_account(current_user.id)
        if not account:
            return CreditAccountResponse(
                id=None,
                user_id=current_user.id,
                balance=0,
                is_checked_in_today=False,
                created_at=None,
                updated_at=None,
            )
        is_checked_in = await credit_service.is_checked_in_today(current_user.id)

        return CreditAccountResponse(
            id=account.id,
            user_id=account.user_id,
            balance=account.balance,
            is_checked_in_today=is_checked_in,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )


@router.post("/checkin")
async def daily_checkin(
    current_user: CurrentUserDep,
    credit_service: CreditServiceDep,
) -> CheckinResponse:
    """执行每日签到，赠送 100 credits。每个用户每天仅限签到一次。"""
    async with credit_service.write() as uow:
        account, tx = await credit_service.daily_checkin(current_user.id)
        result = CheckinResponse(
            success=True,
            balance=account.balance,
            amount_earned=tx.amount,
            expires_at=tx.expires_at
            if tx.expires_at is not None
            else datetime.now(UTC),
        )
        await uow.commit()
    return result


@router.get("/transactions")
async def list_my_transactions(
    current_user: CurrentUserDep,
    credit_service: CreditServiceDep,
    source: Annotated[str | None, Query(max_length=50)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CreditTransactionsListResponse:
    """分页获取当前用户 Credits 账户的额度变动流水记录，可按 source 过滤。"""
    async with credit_service.read():
        transactions, total = await credit_service.list_user_transactions(
            user_id=current_user.id,
            source=source,
            skip=skip,
            limit=limit,
        )

        return CreditTransactionsListResponse(
            items=[
                CreditTransactionResponse.model_validate(transaction)
                for transaction in transactions
            ],
            total=total,
        )
