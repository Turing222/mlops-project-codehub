from fastapi import APIRouter, Depends
from app.api import deps

router = APIRouter()

@router.get("/me")
def read_user_me(
    # 只需要这一行，FastAPI 就会自动执行鉴权和数据库注入
    current_user = Depends(deps.get_current_user)
):
    """获取当前登录用户信息"""
    return current_user

@router.post("/")
def create_user(
    db = Depends(deps.get_db),
    # 这里不需要鉴权，因为注册账号可能是公开的
):
    """创建新用户"""
    pass