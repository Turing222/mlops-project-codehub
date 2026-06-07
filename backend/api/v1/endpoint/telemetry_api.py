"""Frontend telemetry ingestion endpoints.

职责：接收前端精简错误事件遥测并写入结构化日志。
边界：本模块不落库、不触发业务流程，也不承担通用前端监控（metrics/Web Vitals）职责。
"""

import logging
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from backend.api.deps.origin import is_allowed_browser_origin

logger = logging.getLogger(__name__)
router = APIRouter()

# Bound metadata so a misbehaving client cannot push unbounded structured log input.
_METADATA_MAX_KEYS = 20
_METADATA_MAX_VALUE_LENGTH = 2048

MetadataValue = str | int | float | bool | None


class FrontendErrorEventType(StrEnum):
    """Discriminator for the kind of frontend error being reported."""

    http_error = "http_error"
    render_error = "render_error"
    global_error = "global_error"
    unhandled_rejection = "unhandled_rejection"
    stream_error = "stream_error"


class FrontendErrorTelemetry(BaseModel):
    """Generic frontend error event.

    HTTP-specific fields (request_id/status/error_code/url/method) are optional so
    runtime errors (render/global/promise/stream) can be reported without them, while
    API 5xx reports keep their existing request correlation.
    """

    event_type: Annotated[FrontendErrorEventType, Field(alias="eventType")]
    message: Annotated[str, Field(min_length=1, max_length=500)]
    source: Annotated[str, Field(min_length=1, max_length=80)]
    severity: Literal["error"] = "error"
    request_id: Annotated[str | None, Field(alias="requestId", max_length=128)] = None
    status: Annotated[int | None, Field(ge=100, le=599)] = None
    error_code: Annotated[str | None, Field(alias="errorCode", max_length=80)] = None
    url: Annotated[str | None, Field(max_length=2048)] = None
    method: Annotated[str | None, Field(max_length=16)] = None
    metadata: dict[str, MetadataValue] | None = None

    @field_validator("metadata")
    @classmethod
    def _bound_metadata(
        cls, value: dict[str, MetadataValue] | None
    ) -> dict[str, MetadataValue] | None:
        if value is None:
            return value
        if len(value) > _METADATA_MAX_KEYS:
            raise ValueError(
                f"metadata accepts at most {_METADATA_MAX_KEYS} keys",
            )
        for key, item in value.items():
            if isinstance(item, str) and len(item) > _METADATA_MAX_VALUE_LENGTH:
                raise ValueError(
                    f"metadata value for '{key}' exceeds "
                    f"{_METADATA_MAX_VALUE_LENGTH} characters",
                )
        return value


@router.post("/errors", status_code=status.HTTP_204_NO_CONTENT)
async def report_frontend_error(
    payload: FrontendErrorTelemetry,
    request: Request,
) -> Response:
    if not is_allowed_browser_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    telemetry_request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "Frontend error reported",
        extra={
            "event": "frontend_error_reported",
            "telemetry_request_id": telemetry_request_id,
            "frontend_event_type": payload.event_type.value,
            "frontend_source": payload.source,
            "frontend_severity": payload.severity,
            "frontend_message": payload.message,
            "frontend_request_id": payload.request_id,
            "frontend_status": payload.status,
            "frontend_error_code": payload.error_code,
            "frontend_url": payload.url,
            "frontend_method": payload.method,
            "frontend_metadata": payload.metadata,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
