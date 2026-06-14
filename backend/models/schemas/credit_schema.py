"""Credit request and response schemas.

职责：定义 Credits 账户、变动流水等 Pydantic 数据模型。
边界：仅负责 API 输入输出校验与格式转换。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CreditAccountResponse(BaseModel):
    """Credits 账户响应。"""

    id: uuid.UUID | None
    user_id: uuid.UUID
    balance: int
    is_checked_in_today: bool
    created_at: datetime | None
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class CreditTransactionResponse(BaseModel):
    """Credits 交易流水响应。"""

    id: uuid.UUID
    account_id: uuid.UUID
    amount: int
    source: str
    expires_at: datetime | None = None
    idempotency_key: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreditTransactionsListResponse(BaseModel):
    """Credits 变动流水列表响应。"""

    items: list[CreditTransactionResponse]
    total: int


class CheckinResponse(BaseModel):
    """签到结果响应。"""

    success: bool
    balance: int
    amount_earned: int
    expires_at: datetime
