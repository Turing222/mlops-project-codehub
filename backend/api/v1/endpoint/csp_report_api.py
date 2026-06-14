"""CSP report-only ingestion endpoint.

职责：接收浏览器 Content-Security-Policy-Report-Only 违规报告并写入结构化日志。
边界：本模块不落库、不触发告警，也不承担 CSP enforcement。
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.api.deps.origin import is_allowed_browser_origin

logger = logging.getLogger(__name__)
router = APIRouter()


class CspReport(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    document_uri: Annotated[
        str | None, Field(alias="document-uri", max_length=2048)
    ] = None
    blocked_uri: Annotated[str | None, Field(alias="blocked-uri", max_length=2048)] = (
        None
    )
    violated_directive: Annotated[
        str | None,
        Field(alias="violated-directive", max_length=256),
    ] = None
    effective_directive: Annotated[
        str | None,
        Field(alias="effective-directive", max_length=256),
    ] = None
    source_file: Annotated[str | None, Field(alias="source-file", max_length=2048)] = (
        None
    )
    line_number: Annotated[int | None, Field(alias="line-number", ge=0)] = None
    disposition: Annotated[str | None, Field(max_length=80)] = None


class CspReportEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    csp_report: Annotated[CspReport, Field(alias="csp-report")]


@router.post("/reports", status_code=status.HTTP_204_NO_CONTENT)
async def report_csp_violation(
    request: Request,
) -> Response:
    if not is_allowed_browser_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    try:
        payload = CspReportEnvelope.model_validate(await request.json())
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSP 上报内容格式无效",
        ) from exc

    report = payload.csp_report
    telemetry_request_id = getattr(request.state, "request_id", None)
    logger.info(
        "CSP violation reported",
        extra={
            "event": "csp_violation",
            "document_uri": report.document_uri,
            "blocked_uri": report.blocked_uri,
            "violated_directive": report.violated_directive,
            "effective_directive": report.effective_directive,
            "source_file": report.source_file,
            "line_number": report.line_number,
            "disposition": report.disposition,
            "telemetry_request_id": telemetry_request_id,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
