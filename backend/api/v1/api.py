# 业务逻辑汇总
from fastapi import APIRouter

from backend.api.v1.endpoint import auth, user

# , items, login

api_router = APIRouter()

# include_router 会将子文件中的路由“挂载”到总路由下
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(user.router, prefix="/users", tags=["users"])
api_router.include_router(user.router, prefix="/knowledge", tags=["knowledge"])
# api_router.include_router(items.router, prefix="/items", tags=["items"])
