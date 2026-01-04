#依赖注入
#from typing import Generator
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from app.core.database import get_session
from app.models.user import User

# 假设你在 core/config.py 中定义了配置
# 假设你在 core/security.py 中定义了算法
# 假设你在 models/user.py 中定义了数据库模型

reusable_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/login")



async def get_current_user(
    db = Depends(get_session), 
    token: str = Depends(reusable_oauth2)
):
    """
    鉴权中间逻辑：
    1. 尝试解码 JWT token
    2. 校验用户是否存在
    3. 返回用户对象，若失败抛出 401
    """
    try:
        payload = jwt.decode(token, "YOUR_SECRET_KEY", algorithms=["HS256"])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_0403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    
    # 假设从数据库查询用户
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user