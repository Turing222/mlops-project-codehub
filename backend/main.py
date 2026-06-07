import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse

import backend.core.secret_env  # noqa: F401
from backend.api.deps.auth import get_current_superuser
from backend.api.v1.api import api_router
from backend.config.llm import validate_llm_configs
from backend.config.permissions import get_permission_policy
from backend.config.settings import settings
from backend.config.web_settings import is_production_app_env
from backend.core.exception_handlers import setup_exception_handlers
from backend.infra.database import init_db
from backend.infra.redis import redis_client
from backend.middleware.payload_limit import PayloadLimitMiddleware
from backend.middleware.tracing import TracingMiddleware
from backend.models.orm.user import User
from backend.observability.logger import setup_logging
from backend.observability.telemetry import setup_telemetry, shutdown_telemetry

logger = logging.getLogger(__name__)


def _api_docs_urls(app_env: str) -> tuple[str | None, str | None, str | None]:
    if is_production_app_env(app_env):
        return None, None, None
    return "/docs", "/redoc", "/openapi.json"


# 1. 定义生命周期（DBA 关心的资源管理）
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    logger.info("系统初始化完成")

    # 顺序组合不同的初始化逻辑
    # 启动时：可以在这里打印连接池状态
    get_permission_policy()
    validate_llm_configs()
    logger.info("权限与 LLM 配置加载完成")

    async with init_db(app):
        # 初始化 Redis
        await redis_client.init()
        yield
        # 关闭 Redis
        await redis_client.close()
    shutdown_telemetry()
    logger.info("系统已关闭")


_docs_url, _redoc_url, _openapi_url = _api_docs_urls(settings.APP_ENV)

app = FastAPI(
    root_path=settings.API_ROOT_PATH,
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# 全局异常处理
setup_exception_handlers(app)

# Security Middlewares
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,  # type: ignore[arg-type]
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=settings.BACKEND_CORS_METHODS,
        allow_headers=settings.BACKEND_CORS_HEADERS,
        expose_headers=settings.BACKEND_CORS_EXPOSE_HEADERS,
    )
app.add_middleware(PayloadLimitMiddleware)  # type: ignore[arg-type]

# 中间件策略
app.add_middleware(TracingMiddleware)  # type: ignore[arg-type]

# OpenTelemetry 统一遥测初始化 (指标通过 OTLP 推送到 Prometheus)
setup_telemetry(app)

# 路由挂载
app.include_router(api_router, prefix=settings.API_V1_STR)


# index信息
@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "AI Mentor 数据库已就绪！"}


@app.get("/metrics")
def metrics_endpoint() -> PlainTextResponse:
    """Prometheus scrape 健康探针（实际指标通过 OTLP 推送）。"""
    return PlainTextResponse("")


if settings.DEBUG:

    @app.get("/debug-request")
    async def debug_request(
        request: Request,
        _current_user: Annotated[User, Depends(get_current_superuser)],
    ) -> dict[str, object]:
        headers = dict(request.headers)
        client_host = request.client.host if request.client else "unknown"
        client_port = request.client.port if request.client else 0

        debug_info = {
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client": f"{client_host}:{client_port}",
            "headers": headers,
        }

        logger.debug(
            "\n%s\nDEBUG: RECEIVED HTTP REQUEST\n%s\n%s\n",
            "=" * 50,
            json.dumps(debug_info, indent=4),
            "=" * 50,
        )

        return debug_info
