"""Frontend telemetry ingestion endpoints.

职责：接收前端精简错误遥测并写入结构化日志。
边界：本模块不落库、不触发业务流程，也不承担通用前端监控职责。
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.api.deps.origin import is_allowed_browser_origin

logger = logging.getLogger(__name__)
router = APIRouter()


class FrontendErrorTelemetry(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=500)]
    status: Annotated[int, Field(ge=500, le=599)]
    error_code: Annotated[str, Field(alias="errorCode", min_length=1, max_length=80)]
    request_id: Annotated[str, Field(alias="requestId", min_length=1, max_length=128)]
    url: Annotated[str | None, Field(max_length=2048)] = None
    method: Annotated[str | None, Field(max_length=16)] = None
    source: Annotated[str | None, Field(max_length=80)] = None


@router.post("/errors", status_code=status.HTTP_204_NO_CONTENT)
async def report_frontend_error(
    payload: FrontendErrorTelemetry,
    request: Request,
) -> Response:
    if not is_allowed_browser_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    telemetry_request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "Frontend API error reported",
        extra={
            "event": "frontend_api_error",
            "telemetry_request_id": telemetry_request_id,
            "frontend_request_id": payload.request_id,
            "frontend_status": payload.status,
            "frontend_error_code": payload.error_code,
            "frontend_message": payload.message,
            "frontend_url": payload.url,
            "frontend_method": payload.method,
            "frontend_source": payload.source,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
