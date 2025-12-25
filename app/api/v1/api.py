#业务逻辑汇总
from fastapi import APIRouter
from app.api.v1.endpoints import users, items, login

api_router = APIRouter()

# include_router 会将子文件中的路由“挂载”到总路由下
api_router.include_router(login.router, tags=["login"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(items.router, prefix="/items", tags=["items"])