"""Chat API unit tests.

职责：验证 chat endpoint 的 stream event 序列化和审计记录；边界：直接调用 endpoint 函数，不启动 HTTP stack 或真实 worker；副作用：无。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from backend.api.v1.endpoint import chat_api
from backend.models.enums import MessageStatus
from backend.models.schemas.chat.api import MessageResponse
from backend.services.audit_service import AuditService

pytestmark = pytest.mark.asyncio


class CapturingSession:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.audit_repo = self

    async def __aenter__(self) -> CapturingSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def add(self, event: object) -> None:
        self.events.append(event)

    async def commit(self) -> None:
        return None


class CapturingUowFactory:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self) -> CapturingSession:
        return CapturingSession(self.events)


class TypedStreamWorkflow:
    async def handle_query_stream(self, command: Any) -> AsyncIterator[dict[str, str]]:
        message_id = uuid.uuid4()
        yield {
            "type": "meta",
            "session_id": str(command.session_id or uuid.uuid4()),
            "session_title": "demo",
            "message_id": str(message_id),
        }
        yield {"type": "chunk", "content": "hello"}
        yield {"type": "done"}


async def test_query_stream_serializes_typed_events_and_audits_meta_resource() -> None:
    class FakeHttpRequest:
        async def is_disconnected(self) -> bool:
            return False

    uow_factory = CapturingUowFactory()
    audit_service = AuditService(
        uow=SimpleNamespace(),
        independent_uow_factory=uow_factory,
    )
    request = SimpleNamespace(
        query="hello",
        session_id=None,
        kb_id=None,
        client_request_id="client-1",
        enable_external_context=False,
        context_mode=None,
        extra_body=None,
    )

    response = await chat_api.query_stream(
        http_request=FakeHttpRequest(),  # type: ignore
        request=request,
        current_user=SimpleNamespace(id=uuid.uuid4()),
        workflow=TypedStreamWorkflow(),
        _=None,
        audit_service=audit_service,
    )

    chunks = [chunk async for chunk in response.body_iterator]

    assert chunks[0].startswith('data: {"type": "meta"')
    assert chunks[1] == 'data: {"type": "chunk", "content": "hello"}\n\n'
    assert chunks[2] == "data: [DONE]\n\n"
    assert len(uow_factory.events) == 1
    assert uow_factory.events[0].resource_type == "chat_session"
    assert uow_factory.events[0].resource_id is not None


async def test_message_response_includes_message_metadata() -> None:
    message_id = uuid.uuid4()
    session_id = uuid.uuid4()
    response = MessageResponse.model_validate(
        {
            "id": message_id,
            "session_id": session_id,
            "role": "assistant",
            "content": "answer",
            "status": MessageStatus.SUCCESS,
            "latency_ms": 10,
            "search_context": None,
            "message_metadata": {"metrics": {"first_token_latency_ms": 123}},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    )

    assert response.message_metadata["metrics"]["first_token_latency_ms"] == 123
