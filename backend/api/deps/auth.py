import logging

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError as PydanticValidationError

from backend.api.deps.uow import get_uow
from backend.core.config import settings
from backend.core.exceptions import (
    app_bad_request,
    app_forbidden,
    app_not_found,
    app_validation_error,
)
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.user import User
from backend.models.schemas.user_schema import UserLogin
from backend.services.user_service import UserService

reusable_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
logger = logging.getLogger(__name__)


def get_login_data(
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> UserLogin:
    try:
        return UserLogin(
            username=form_data.username,
            password=form_data.password,
        )
    except PydanticValidationError as exc:
        raise app_validation_error("请求参数校验失败", details={"errors": exc.errors()}) from exc


async def get_current_user(
    uow: AbstractUnitOfWork = Depends(get_uow),
    token: str = Depends(reusable_oauth2),
) -> User:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise app_forbidden("Token 缺少身份标识", code="TOKEN_SUBJECT_MISSING")
    except (InvalidTokenError, PydanticValidationError) as e:
        raise app_forbidden("Token 无效或已过期", code="INVALID_TOKEN") from e

    logger.debug("Current value of x: %s, type: %s", user_id, type(user_id))

    async with uow:
        user = await UserService(uow).get_by_id(user_id)

    if not user:
        raise app_not_found("用户不存在", code="USER_NOT_FOUND")
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise app_bad_request("用户账户未激活", code="USER_INACTIVE")
    return current_user


def get_current_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    if not current_user.is_superuser:
        raise app_forbidden("权限不足")
    return current_user
