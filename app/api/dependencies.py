# app/api/dependencies.py
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from app.core.database import get_session  # 假设这是你获取 session 的地方
from app.core.security import ALGORITHM, SECRET_KEY
from app.models.orm.user import User
from app.repositories.user_repo import UserRepository


# 1. 这里的逻辑只负责：拿连接 -> 实例化 Repo
async def get_user_repo(session: AsyncSession = Depends(get_session)) -> UserRepository:
    return UserRepository(session)


# 指向你的登录接口 URL，这样 Swagger UI 里的 "Authorize" 按钮才能工作
reusable_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    session: Session = Depends(get_session), token: str = Depends(reusable_oauth2)
) -> User:
    """
    核心鉴权依赖：
    1. 解析 Token
    2. 验证 Token 有效性
    3. 查询数据库获取 User 对象
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=403, detail="Token 缺少身份标识")
    except (JWTError, ValidationError) as e:
        raise HTTPException(status_code=403, detail="Token 无效或已过期") from e

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """校验用户是否处于激活状态（用于封禁逻辑）"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="用户账户未激活")
    return current_user


def get_current_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """权限校验：仅限超级管理员"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="权限不足")
    return current_user
