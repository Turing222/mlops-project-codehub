"""Frontend telemetry ingestion endpoints.

职责：接收前端精简错误事件与 Web Vitals 性能指标遥测，并写入结构化日志。
边界：本模块不落库、不触发业务流程；错误与指标走各自独立的 schema 与日志事件
（frontend_error_reported / frontend_metric_reported），互不混淆。
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


class FrontendMetricName(StrEnum):
    """Web Vitals 指标名（INP 已取代 FID，本端点不收 FID）。"""

    LCP = "LCP"
    INP = "INP"
    CLS = "CLS"
    FCP = "FCP"
    TTFB = "TTFB"


class FrontendMetricRating(StrEnum):
    """web-vitals 给出的 good/needs-improvement/poor 阈值评级。"""

    good = "good"
    needs_improvement = "needs-improvement"
    poor = "poor"


class FrontendMetricNavigationType(StrEnum):
    """web-vitals Metric.navigationType 全集（含 bfcache/prerender/restore），避免误判 422。"""

    navigate = "navigate"
    reload = "reload"
    back_forward = "back-forward"
    back_forward_cache = "back-forward-cache"
    prerender = "prerender"
    restore = "restore"


class FrontendMetricTelemetry(BaseModel):
    """单条 Web Vitals 性能指标事件，与 FrontendErrorTelemetry 完全独立。"""

    name: FrontendMetricName
    value: Annotated[float, Field(ge=0)]
    rating: FrontendMetricRating
    id: Annotated[str, Field(min_length=1, max_length=128)]
    navigation_type: Annotated[
        FrontendMetricNavigationType | None, Field(alias="navigationType")
    ] = None
    url: Annotated[str | None, Field(max_length=2048)] = None
    page: Annotated[str | None, Field(max_length=512)] = None


@router.post("/metrics", status_code=status.HTTP_204_NO_CONTENT)
async def report_frontend_metric(
    payload: FrontendMetricTelemetry,
    request: Request,
) -> Response:
    if not is_allowed_browser_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    telemetry_request_id = getattr(request.state, "request_id", None)
    # info 级：指标是常规观测信号，不同于 error 通道的 warning。
    logger.info(
        "Frontend metric reported",
        extra={
            "event": "frontend_metric_reported",
            "telemetry_request_id": telemetry_request_id,
            "frontend_metric_name": payload.name.value,
            "frontend_metric_value": payload.value,
            "frontend_metric_rating": payload.rating.value,
            "frontend_metric_id": payload.id,
            "frontend_metric_navigation_type": (
                payload.navigation_type.value
                if payload.navigation_type is not None
                else None
            ),
            "frontend_metric_url": payload.url,
            "frontend_metric_page": payload.page,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
