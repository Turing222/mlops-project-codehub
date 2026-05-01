"""LLM routing service.

职责：按候选顺序尝试多个 LLM 服务，用于 profile 或 API key fallback。
边界：流式输出一旦发出 chunk 就不能安全切换候选。
失败处理：所有候选失败时返回包含尝试摘要的统一业务错误。
"""

import logging
import time
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass

from backend.contracts.interfaces import AbstractLLMService
from backend.core.exceptions import app_service_error
from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LLMRouteCandidate:
    """一个可被路由尝试的 LLM 候选。"""

    label: str
    service: AbstractLLMService


class LLMRoutingService(AbstractLLMService):
    """按顺序尝试 LLM 候选并处理 fallback。"""

    def __init__(self, candidates: Sequence[LLMRouteCandidate]) -> None:
        if not candidates:
            raise ValueError("LLM routing service requires at least one candidate")
        self.candidates = tuple(candidates)

    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        errors: list[dict[str, str]] = []

        for index, candidate in enumerate(self.candidates):
            chunk_seen = False
            try:
                async for chunk in candidate.service.stream_response(query):
                    chunk_seen = True
                    yield chunk
                return
            except Exception as exc:
                errors.append(_error_details(candidate.label, exc))
                if chunk_seen:
                    logger.warning(
                        "LLM stream candidate failed after chunks were sent; "
                        "cannot switch safely: candidate=%s",
                        candidate.label,
                        exc_info=True,
                    )
                    raise

                if index == len(self.candidates) - 1:
                    break

                logger.warning(
                    "LLM stream candidate failed, switching to next: candidate=%s",
                    candidate.label,
                    exc_info=True,
                )

        raise app_service_error(
            "LLM 路由所有候选均失败",
            code="LLM_ROUTING_FAILED",
            details={"session_id": str(query.session_id), "attempts": errors},
        )

    async def generate_response(
        self,
        query: LLMQueryDTO,
    ) -> LLMResultDTO:
        start = time.perf_counter()
        errors: list[dict[str, str]] = []

        for index, candidate in enumerate(self.candidates):
            try:
                result = await candidate.service.generate_response(query)
                result.latency_ms = int((time.perf_counter() - start) * 1000)
                return result
            except Exception as exc:
                errors.append(_error_details(candidate.label, exc))
                if index == len(self.candidates) - 1:
                    break

                logger.warning(
                    "LLM candidate failed, switching to next: candidate=%s",
                    candidate.label,
                    exc_info=True,
                )

        raise app_service_error(
            "LLM 路由所有候选均失败",
            code="LLM_ROUTING_FAILED",
            details={"session_id": str(query.session_id), "attempts": errors},
        )


def _error_details(label: str, exc: Exception) -> dict[str, str]:
    status_code = getattr(_root_cause(exc), "status_code", None)
    details = {
        "candidate": label,
        "error": str(exc),
        "type": type(exc).__name__,
    }
    if status_code is not None:
        details["status_code"] = str(status_code)
    return details


def _root_cause(exc: BaseException) -> BaseException:
    current = exc
    while current.__cause__ is not None:
        current = current.__cause__
    return current
