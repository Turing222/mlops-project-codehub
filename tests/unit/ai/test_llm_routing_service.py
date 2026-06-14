"""LLM routing service unit tests.

职责：验证多候选 LLM 生成和流式生成的 fallback 行为；边界：使用 stub LLM service，不访问真实模型服务；副作用：无。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest

from backend.ai.providers.llm.routing_service import (
    LLMRouteCandidate,
    LLMRoutingService,
)
from backend.contracts.interfaces import AbstractLLMService
from backend.core.exceptions import app_service_error
from backend.models.schemas.chat.dto import LLMQueryDTO, LLMResultDTO

pytestmark = pytest.mark.asyncio


def make_query() -> LLMQueryDTO:
    return LLMQueryDTO(
        session_id=uuid.uuid4(),
        query_text="当前问题",
        conversation_history=[],
    )


class FailingLLMService(AbstractLLMService):
    @property
    def model_name(self) -> str:
        return "failing-model"

    @property
    def provider_name(self) -> str:
        return "failing-provider"

    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        raise app_service_error("rate limited", details={"status_code": 429})
        yield ""

    async def generate_response(self, query: LLMQueryDTO) -> LLMResultDTO:
        raise app_service_error("rate limited", details={"status_code": 429})


class SuccessfulLLMService(AbstractLLMService):
    @property
    def model_name(self) -> str:
        return "success-model"

    @property
    def provider_name(self) -> str:
        return "success-provider"

    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        yield "fallback "
        yield "answer"

    async def generate_response(self, query: LLMQueryDTO) -> LLMResultDTO:
        return LLMResultDTO(content="fallback answer", latency_ms=12)


async def test_generate_response_falls_back_to_next_candidate() -> None:
    service = LLMRoutingService(
        [
            LLMRouteCandidate("primary", FailingLLMService()),
            LLMRouteCandidate("fallback", SuccessfulLLMService()),
        ]
    )

    result = await service.generate_response(make_query())

    assert result.content == "fallback answer"
    assert result.success is True


async def test_stream_response_falls_back_before_first_chunk() -> None:
    service = LLMRoutingService(
        [
            LLMRouteCandidate("primary", FailingLLMService()),
            LLMRouteCandidate("fallback", SuccessfulLLMService()),
        ]
    )

    chunks = [chunk async for chunk in service.stream_response(make_query())]

    assert chunks == ["fallback ", "answer"]
