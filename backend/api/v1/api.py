from fastapi import APIRouter, Depends

from backend.api.v1.endpoint import (
    audit_api,
    auth_api,
    chat_api,
    credit_api,
    csp_report_api,
    health_check,
    knowledge_api,
    permission_api,
    repo_analysis_api,
    telemetry_api,
    user_api,
    workspace_api,
)
from backend.config.settings import settings
from backend.middleware.rate_limit import RateLimiter

api_router = APIRouter()
business_limiter = RateLimiter(
    times=settings.BUSINESS_RATE_LIMIT_TIMES,
    seconds=settings.BUSINESS_RATE_LIMIT_SECONDS,
)
frontend_telemetry_limiter = RateLimiter(
    times=settings.FRONTEND_TELEMETRY_RATE_LIMIT_TIMES,
    seconds=settings.FRONTEND_TELEMETRY_RATE_LIMIT_SECONDS,
)
csp_report_limiter = RateLimiter(
    times=settings.CSP_REPORT_RATE_LIMIT_TIMES,
    seconds=settings.CSP_REPORT_RATE_LIMIT_SECONDS,
)

api_router.include_router(
    auth_api.router,
    prefix="/auth",
    tags=["auth"],
)
api_router.include_router(
    user_api.router,
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(business_limiter)],
)
api_router.include_router(chat_api.router, prefix="/chat", tags=["chat"])
api_router.include_router(
    knowledge_api.router,
    prefix="/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(business_limiter)],
)
api_router.include_router(
    audit_api.router,
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(business_limiter)],
)
api_router.include_router(
    workspace_api.router,
    prefix="/workspaces",
    tags=["workspaces"],
    dependencies=[Depends(business_limiter)],
)
api_router.include_router(
    permission_api.router,
    prefix="/permissions",
    tags=["permissions"],
    dependencies=[Depends(business_limiter)],
)
api_router.include_router(
    telemetry_api.router,
    prefix="/telemetry",
    tags=["telemetry"],
    dependencies=[Depends(frontend_telemetry_limiter)],
)
api_router.include_router(
    csp_report_api.router,
    prefix="/csp",
    tags=["csp"],
    dependencies=[Depends(csp_report_limiter)],
)
api_router.include_router(
    credit_api.router,
    prefix="/credits",
    tags=["credits"],
    dependencies=[Depends(business_limiter)],
)
api_router.include_router(
    repo_analysis_api.router,
    prefix="/repo-analysis",
    tags=["repo-analysis"],
    dependencies=[Depends(business_limiter)],
)
api_router.include_router(
    health_check.router, prefix="/health_check", tags=["health_check"]
)
