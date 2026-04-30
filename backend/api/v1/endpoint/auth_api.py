from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_audit_service, get_login_data, get_uow
from backend.core.config import settings
from backend.core.exceptions import app_bad_request
from backend.core.security import create_access_token
from backend.models.orm.access import AuditOutcome
from backend.models.schemas.user_schema import (
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from backend.services.audit_service import AuditAction, AuditService, record_audit
from backend.services.unit_of_work import AbstractUnitOfWork
from backend.services.user_service import UserService

router = APIRouter()
UOW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
LoginDataDep = Annotated[UserLogin, Depends(get_login_data)]


@router.post("/register", response_model=UserResponse)
async def register(user_in: UserCreate, uow: UOW) -> UserResponse:
    async with uow:
        user = await UserService(uow).user_register_with_personal_workspace(user_in)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=Token)
async def login(
    login_data: LoginDataDep,
    uow: UOW,
    audit_service: AuditService = Depends(get_audit_service),
) -> Token:
    # 1. 调用 Service 验证
    async with uow:
        user = await UserService(uow).authenticate(login_data)
        if not user:
            await record_audit(
                audit_service,
                action=AuditAction.AUTH_LOGIN_FAILED,
                outcome=AuditOutcome.FAILED,
                metadata={
                    "username": login_data.username,
                    "reason": "bad_credentials",
                },
            )
            raise app_bad_request("用户名或密码错误", code="BAD_CREDENTIALS")

        if not user.is_active:
            await record_audit(
                audit_service,
                action=AuditAction.AUTH_LOGIN_FAILED,
                actor_user_id=user.id,
                outcome=AuditOutcome.FAILED,
                metadata={
                    "username": login_data.username,
                    "reason": "inactive_user",
                },
            )
            raise app_bad_request("账户未激活", code="USER_INACTIVE")

    # 2. 发放 Token (Token 生成是纯 CPU 计算，无需 await)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
    )
    await record_audit(
        audit_service,
        action=AuditAction.AUTH_LOGIN_SUCCESS,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        metadata={"username": login_data.username},
    )
    return Token(access_token=access_token, token_type="bearer")
