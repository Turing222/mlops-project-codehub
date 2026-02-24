import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from backend.api.v1.api import api_router
from backend.core.config import settings
from backend.core.database import init_db
from backend.core.exceptions import setup_exception_handlers
from backend.core.logger import setup_logging
from backend.middleware.tracing import setup_tracing
from backend.core.redis import redis_client

# 1. 初始化
setup_logging()

# 2. 获取 logger
logger = logging.getLogger(__name__)

# 3. 产生日志
logger.info("系统初始化完成")


# 1. 定义生命周期（DBA 关心的资源管理）
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 顺序组合不同的初始化逻辑
    # 启动时：可以在这里打印连接池状态
    print("🚀 System starting...")
    async with init_db(app):
        # 初始化 Redis
        await redis_client.init()
        yield
        # 关闭 Redis
        await redis_client.close()
    print("🛑 System shutting down...")


app = FastAPI(
    root_path="/api",
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# 全局异常处理
setup_exception_handlers(app)

# 中间件
setup_tracing(app)

# 前缀名「方案选单」
app.include_router(api_router, prefix="/v1")


# index信息
@app.get("/")
def read_root():
    return {"message": "AI Mentor 数据库已就绪！"}


@app.get("/debug-request")
async def debug_request(request: Request):
    # 1. 提取所有 Header
    headers = dict(request.headers)

    # 2. 提取客户端信息（此时应该是 Nginx 的内网 IP，除非配了 proxy_headers）
    client_host = request.client.host if request.client else "unknown"
    client_port = request.client.port if request.client else 0

    # 3. 提取请求的基础信息
    debug_info = {
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path,
        "query_params": dict(request.query_params),
        "client": f"{client_host}:{client_port}",
        "headers": headers,
    }

    # 4. 在控制台打印出来（重点看 X-Real-IP 和 X-Request-ID）
    print("\n" + "=" * 50)
    print("DEBUG: RECEIVED HTTP REQUEST")
    print(json.dumps(debug_info, indent=4))
    print("=" * 50 + "\n")

    return debug_info
