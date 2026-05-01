import uuid
from collections.abc import AsyncGenerator

import pytest

from backend.ai.providers.llm.routing_service import (
    LLMRouteCandidate,
    LLMRoutingService,
)
from backend.contracts.interfaces import AbstractLLMService
from backend.core.exceptions import app_service_error
from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO


def make_query() -> LLMQueryDTO:
    return LLMQueryDTO(
        session_id=uuid.uuid4(),
        query_text="当前问题",
        conversation_history=[],
    )


class FailingLLMService(AbstractLLMService):
    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        raise app_service_error("rate limited", details={"status_code": 429})
        yield ""

    async def generate_response(self, query: LLMQueryDTO) -> LLMResultDTO:
        raise app_service_error("rate limited", details={"status_code": 429})


class SuccessfulLLMService(AbstractLLMService):
    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        yield "fallback "
        yield "answer"

    async def generate_response(self, query: LLMQueryDTO) -> LLMResultDTO:
        return LLMResultDTO(content="fallback answer", latency_ms=12)


@pytest.mark.asyncio
async def test_generate_response_falls_back_to_next_candidate():
    service = LLMRoutingService(
        [
            LLMRouteCandidate("primary", FailingLLMService()),
            LLMRouteCandidate("fallback", SuccessfulLLMService()),
        ]
    )

    result = await service.generate_response(make_query())

    assert result.content == "fallback answer"
    assert result.success is True


@pytest.mark.asyncio
async def test_stream_response_falls_back_before_first_chunk():
    service = LLMRoutingService(
        [
            LLMRouteCandidate("primary", FailingLLMService()),
            LLMRouteCandidate("fallback", SuccessfulLLMService()),
        ]
    )

    chunks = [chunk async for chunk in service.stream_response(make_query())]

    assert chunks == ["fallback ", "answer"]
