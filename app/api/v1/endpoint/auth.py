from datetime import timedelta
from typing import Any

from app.schemas.user import Token, UserCreate, UserPublic
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel.ext.asyncio.session import AsyncSession  # ⚠️ 引用异步 Session

from app.api.deps import get_session
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
from app.services.user_auth_service import UserService  # ⚠️ 引用 Service

router = APIRouter()


@router.post("/register", response_model=UserPublic)
async def register(
    user_in: UserCreate, session: AsyncSession = Depends(get_session)
) -> Any:
    # 1. 检查唯一性
    await UserService.get_by_email(session, user_in.email)
    await UserService.get_by_username(session, user_in.username)

    # 2. 调用 Service 创建
    user = await UserService.create(session, user_in)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
) -> Any:
    # 1. 调用 Service 验证
    user = await UserService.authenticate(
        session, username=form_data.username, password=form_data.password
    )

    if not user:
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="账户未激活")

    # 2. 发放 Token (Token 生成是纯 CPU 计算，无需 await)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
    }
