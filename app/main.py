#串联所有程序
from fastapi import FastAPI, Depends
from sqlmodel import Session, select
from app.core.database import get_session,engine  # 假设你把 create_engine 放在了 database.py
from models import User      # 假设你把 User 类放在了 models.py
from contextlib import asynccontextmanager
from app.api.v1.api import api_router

# 1. 定义生命周期（DBA 关心的资源管理）
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：可以在这里打印连接池状态
    print("🚀 System starting...")
    yield
    # 关闭时：优雅断开数据库连接
    print("🛑 System shutting down...")
    await engine.dispose()

app = FastAPI(
    title="我的AI Mentor后台系统", 
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
def read_root():
    return {"message": "AI Mentor 数据库已就绪！"}

app.include_router(api_router, prefix="/api/v1")
