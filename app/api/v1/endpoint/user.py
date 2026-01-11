from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.api.params import LimitParam, SkipParam, UsernameQuery
from app.core.database import get_session
from app.crud.user import create_user, get_users, upsert_users
from app.schemas.user import UserPublic
from app.services.user_service import process_user_import

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
@router.get("/users",response_model=list[UserPublic])
async def read_users(
    session: AsyncSession = Depends(get_session),
    username: UsernameQuery = None, # 使用我们定义的类型，默认为 None
    skip: SkipParam = 0,
    limit: LimitParam = 10
    ):
    users = await get_users(session, username=username, skip=skip, limit=limit)
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
async def create_user_once(
    session: AsyncSession = Depends(get_session)):
    await create_user(session,)
    return {"status": "成功", "user": "admin"}

# 接口：通过文件上传批量插入客户
@router.post("/init-data")
async def csv_balk_insert_users(session: AsyncSession = Depends(get_session)):
    mock_data = [
        {"username": "admin", "email": "admin@bank.com"},
        {"username": "dba_master", "email": "dba@bank.com"}
    ]
    await process_user_import(session, mock_data)
    return {"status": "成功", "user": "admin"}