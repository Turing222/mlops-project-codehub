import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import ValidationError

from backend.core.config import settings
from backend.core.database import async_session_maker
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.user import User
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.services.user_service import UserService

# 指向你的登录接口 URL，这样 Swagger UI 里的 "Authorize" 按钮才能工作
reusable_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

logger = logging.getLogger(__name__)


# 每次请求，实例化一个新的 UoW
async def get_uow():
    return SQLAlchemyUnitOfWork(async_session_maker)


async def get_current_user(
    # 1. 嵌套注入：直接拿到 service 实例
    uow: AbstractUnitOfWork = Depends(get_uow),
    token: str = Depends(reusable_oauth2),
) -> User:  # 注意：内部逻辑可以用 ORM，但为了后续属性访问，这里先返回 ORM 对象
    """
    核心鉴权依赖：
    1. 解析并验证 Token
    2. 通过 Service 层获取 User 实体
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Token 缺少身份标识"
            )
    except (JWTError, ValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Token 无效或已过期"
        ) from e

    # 2. 调用 Service 层而不是 session.get
    # 这样以后你在 service 里加缓存或预加载(joinedload)逻辑，这里都会自动受益
    logger.debug(f"Current value of x: {user_id}, type: {type(user_id)}")

    async with uow:
        user = await UserService(uow).get_by_id(user_id)

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """校验用户是否处于激活状态"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="用户账户未激活"
        )
    return current_user


def get_current_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """权限校验：仅限超级管理员"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return current_user
