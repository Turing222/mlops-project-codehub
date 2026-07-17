"""Session detail projection tests for durable Chat generation identity."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.models.enums import ChatGenerationStatus, MessageStatus
from backend.services.session_query_service import SessionQueryService


async def test_session_detail_enriches_failed_assistant_with_generation_state() -> None:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    message_id = uuid.uuid4()
    request_id = uuid.uuid4()
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id=session_id,
        title="Retryable session",
        user_id=user_id,
        kb_id=None,
        llm_config={},
        created_at=now,
        updated_at=now,
    )
    message = SimpleNamespace(
        id=message_id,
        session_id=session_id,
        role="assistant",
        content="provider failed",
        status=MessageStatus.FAILED,
        latency_ms=None,
        search_context=None,
        message_metadata={},
        created_at=now,
        updated_at=now,
    )
    generation_request = SimpleNamespace(
        id=request_id,
        assistant_message_id=message_id,
        status=ChatGenerationStatus.FAILED,
        attempt=2,
        retryable=True,
        error_code="LLM_TIMEOUT",
    )
    chat_repo = AsyncMock()
    chat_repo.get_session.return_value = session
    chat_repo.get_session_messages.return_value = [message]
    chat_repo.get_generation_requests_for_session_for_actor.return_value = [
        generation_request
    ]
    chat_repo.count_session_messages.return_value = 1
    chat_repo.get_session_total_tokens.return_value = 0
    service = SessionQueryService(SimpleNamespace(chat_repo=chat_repo))

    detail = await service.get_user_session_detail(
        user_id=user_id,
        session_id=session_id,
    )

    assert detail.messages[0].generation_request_id == request_id
    assert detail.messages[0].attempt == 2
    assert detail.messages[0].retryable is True
    assert detail.messages[0].error_code == "LLM_TIMEOUT"
    chat_repo.get_generation_requests_for_session_for_actor.assert_awaited_once_with(
        session_id=session_id,
        user_id=user_id,
    )
