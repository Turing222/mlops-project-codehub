# 业务逻辑汇总
from fastapi import APIRouter

from backend.api.v1.endpoint import auth_api, chat_api, health_check, user_api

# , items, login

api_router = APIRouter()

# include_router 会将子文件中的路由“挂载”到总路由下
api_router.include_router(auth_api.router, prefix="/auth", tags=["auth"])
api_router.include_router(user_api.router, prefix="/users", tags=["users"])
api_router.include_router(chat_api.router, prefix="/chat", tags=["chat"])
# api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(
    health_check.router, prefix="/health_check", tags=["health_check"]
)
# api_router.include_router(items.router, prefix="/items", tags=["items"])
