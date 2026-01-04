from fastapi import APIRouter, Depends
from app.api import deps
from app.core.database import get_session
from app.crud.user import get_users, upsert_users,create_user
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()

'''
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
'''

# 路由：查询用户
@router.get("/users")
async def read_users(
    session: AsyncSession = Depends(get_session)):
    users = await get_users(session)
    return users

# 路由：初始化种子数据
@router.post("/init-data")
async def seed_data(session: AsyncSession = Depends(get_session)):
    mock_data = [
        {"username": "admin", "email": "admin@bank.com"},
        {"username": "dba_master", "email": "dba@bank.com"}
    ]
    await upsert_users(session, mock_data)
    return {"detail": "Seed data processed"}

# 接口：创建一个新用户
@router.post("/users/")

async def read_users(
    session: AsyncSession = Depends(get_session)):
    await create_user(session,)
    return {"status": "成功", "user": "admin"}