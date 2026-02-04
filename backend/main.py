from contextlib import asynccontextmanager
from fastapi import FastAPI
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
print(ROOT)
sys.path.insert(0, str(ROOT))


from backend.core.config import settings
from backend.core.database import engine
from backend.core.logger import setup_logging
from backend.api.v1.api import api_router
from backend.core.exceptions import setup_exception_handlers
import logging

# 1. 初始化
setup_logging()

# 2. 获取 logger
logger = logging.getLogger(__name__)

# 3. 产生日志
logger.info("系统初始化完成")


# 1. 定义生命周期（DBA 关心的资源管理）
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：可以在这里打印连接池状态
    print("🚀 System starting...")
    yield
    # 关闭时：优雅断开数据库连接
    print("🛑 System shutting down...")
    await engine.dispose()


app = FastAPI(title="我的AI Mentor后台系统", version="1.0.0", lifespan=lifespan)

# 全局异常处理
setup_exception_handlers(app)


# index信息
@app.get("/")
def read_root():
    return {"message": "AI Mentor 数据库已就绪！"}


# 前缀名
app.include_router(api_router, prefix="/api/v1")
