from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.api.deps import get_current_active_user, get_session
from app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.models.orm.user import User
from app.models.schemas.user import Token, UserCreate, UserPublic

router = APIRouter()


@router.post("/register", response_model=UserPublic)
def register(user_in: UserCreate, session: Session = Depends(get_session)) -> Any:
    """
    用户注册
    """
    # 1. 检查邮箱是否已存在
    statement = select(User).where(User.email == user_in.email)
    if session.exec(statement).first():
        raise HTTPException(status_code=400, detail="该邮箱已被注册")

    # 2. 检查用户名
    statement = select(User).where(User.username == user_in.username)
    if session.exec(statement).first():
        raise HTTPException(status_code=400, detail="该用户名已被占用")

    # 3. 创建用户 (密码加密)
    user = User.model_validate(
        user_in, update={"hashed_password": get_password_hash(user_in.password)}
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(
    session: Session = Depends(get_session),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    OAuth2 兼容的登录接口
    注意：form_data.username 接收的是用户名或邮箱，取决于前端传什么
    """
    # 1. 查询用户 (支持邮箱登录逻辑可选，这里假设只用 username)
    statement = select(User).where(User.username == form_data.username)
    user = session.exec(statement).first()

    # 2. 验证密码
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="账户未激活")

    # 3. 生成 Token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.get("/me", response_model=UserPublic)
def read_users_me(current_user: User = Depends(get_current_active_user)):
    """
    测试接口：获取当前登录用户信息
    """
    return current_user
