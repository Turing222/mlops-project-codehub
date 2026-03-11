from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_login_data, get_uow
from backend.core.config import settings
from backend.core.security import create_access_token
from backend.models.schemas.user_schema import (
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from backend.services.unit_of_work import AbstractUnitOfWork
from backend.services.user_service import UserService

router = APIRouter()
UOW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
LoginDataDep = Annotated[UserLogin, Depends(get_login_data)]


@router.post("/register", response_model=UserResponse)
async def register(user_in: UserCreate, uow: UOW) -> UserResponse:
    async with uow:
        user = await UserService(uow).user_register(user_in)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=Token)
async def login(
    login_data: LoginDataDep,
    uow: UOW,
) -> Token:
    # 1. 调用 Service 验证
    async with uow:
        user = await UserService(uow).authenticate(login_data)
        if not user:
            raise HTTPException(status_code=400, detail="用户名或密码错误")

        if not user.is_active:
            raise HTTPException(status_code=400, detail="账户未激活")

    # 2. 发放 Token (Token 生成是纯 CPU 计算，无需 await)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")
