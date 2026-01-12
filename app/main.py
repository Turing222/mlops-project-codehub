#串联所有程序
from contextlib import asynccontextmanager

from fastapi import FastAPI

import sys

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
print(ROOT)
sys.path.insert(0, str(ROOT))


from app.core.config import settings
from app.core.database import engine
from app.core.logger import setup_logging
from app.api.v1.api import api_router
from app.core.exceptions import setup_exception_handlers

import logging

# 1. 初始化
setup_logging()

# 2. 获取 logger
logger = logging.getLogger(__name__)

# 3. 产生日志
logger.info("系统初始化完成")
try:
    1 / 1
except Exception as e:
    # exc_info=True 会自动把堆栈信息放入 JSON 的 exception 字段
    logger.error("计算发生了错误", exc_info=True)



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

setup_exception_handlers(app)

@app.get("/")
def read_root():
    return {"message": "AI Mentor 数据库已就绪！"}

app.include_router(api_router, prefix="/api/v1")
