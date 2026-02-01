from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import get_user_service, get_uow
from app.core.config import settings
from app.core.security import create_access_token
from app.models.schemas.user import Token, UserCreate, UserLogin, UserResponse
from app.services.user_service import UserService
from app.services.unit_of_work import AbstractUnitOfWork

router = APIRouter()
# UserServiceDep = Annotated[UserService, Depends(get_user_service)]


@router.post("/register", response_model=UserResponse)
async def register(
    user_in: UserCreate, uow: AbstractUnitOfWork = Depends(get_uow)
) -> Any:
    async with uow:
        user = await UserService(uow).user_register(user_in)
    return user


@router.post("/login", response_model=Token)
async def login(
    uow: AbstractUnitOfWork = Depends(get_uow),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    # 1. 调用 Service 验证
    async with uow:
        login_data = UserLogin(username=form_data.username, password=form_data.password)
        user = await UserService(uow).authenticate(login_data)
        if not user:
            raise HTTPException(status_code=400, detail="用户名或密码错误")

        if not user.is_active:
            raise HTTPException(status_code=400, detail="账户未激活")

        # 2. 发放 Token (Token 生成是纯 CPU 计算，无需 await)
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            subject=user.id, expires_delta=access_token_expires
        )
    return {
        "access_token": access_token,
        "token_type": "bearer",
    }
