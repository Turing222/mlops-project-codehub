"""Chat stream workflow construction and history projection tests.

职责：验证 ChatWorkflow 轻量构造和 history_to_conversation_messages 的消息过滤；
边界：不启动 HTTP stack、不依赖 AI 服务；副作用：无。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from backend.application.chat.history_projection import history_to_conversation_messages
from backend.application.chat.session_orchestrator import (
    ChatIdempotencyState,
    ChatPreparedRequest,
)
from backend.application.chat.stream_events import (
    encode_done_event,
    encode_started_event,
)
from backend.application.chat.web_stream_workflow import ChatWorkflow
from backend.models.enums import ChatGenerationStatus, MessageStatus
from backend.models.schemas.chat.commands import (
    ChatQueryCommand,
    RetryChatGenerationCommand,
)
from backend.models.schemas.chat.payloads import (
    GenerationAttemptPayload,
    GenerationPayload,
)
from backend.services.feature_flag_service import (
    _AI_SYSTEM_FLAG_DEFAULTS,
    FeatureFlagService,
)


def _make_mock_feature_flag_service(
    overrides: dict[str, bool] | None = None,
) -> AsyncMock:
    flags = {
        **_AI_SYSTEM_FLAG_DEFAULTS,
        "enable-public-registration": True,
        "enable-closed-beta-login": False,
        **(overrides or {}),
    }
    svc = AsyncMock(spec=FeatureFlagService)
    svc.get_system_features = AsyncMock(return_value=flags)
    svc.get_user_features = AsyncMock(
        return_value={"chat-explicit-retry": flags.get("chat-explicit-retry", False)}
    )
    return svc


class FakeUow:
    def __init__(self, chat_repo: object) -> None:
        self.chat_repo = chat_repo

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class FakePubSub:
    def __init__(self) -> None:
        self.subscribe = AsyncMock()
        self.unsubscribe = AsyncMock()
        self.aclose = AsyncMock()

    def listen(self):
        async def _events():
            yield {"type": "message", "data": encode_started_event()}
            yield {"type": "message", "data": encode_done_event()}

        return _events()


class FakeStreamRedis:
    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> FakePubSub:
        return self._pubsub


def test_stream_workflow_constructs_without_ai_dependencies() -> None:
    workflow = ChatWorkflow(
        uow=cast(Any, SimpleNamespace()),
        dispatcher=cast(Any, SimpleNamespace()),
        redis_client=cast(Any, SimpleNamespace()),
        permission_service=cast(Any, SimpleNamespace()),
        feature_flag_service=_make_mock_feature_flag_service(),
    )

    assert workflow is not None


async def test_stream_workflow_queues_and_dispatches_before_meta() -> None:
    user_id = uuid.uuid4()
    session = SimpleNamespace(id=uuid.uuid4(), title="Session")
    assistant_message = SimpleNamespace(id=uuid.uuid4())
    generation_request = SimpleNamespace(id=uuid.uuid4(), attempt=1)
    prepared = ChatPreparedRequest(
        session=cast(Any, session),
        generation_request=cast(Any, generation_request),
        assistant_message=cast(Any, assistant_message),
        generation_payload=GenerationPayload(
            session_id=session.id,
            query_text="hello",
        ),
        lock_key="lock:test",
        lock_token="processing:test",
        trace_attrs={},
    )
    generation_attempt = GenerationAttemptPayload(
        request_id=generation_request.id,
        attempt=1,
        task_id="task-stream",
        lease_token="lease-stream",
    )
    dispatcher = AsyncMock()
    pubsub = FakePubSub()
    workflow = ChatWorkflow(
        uow=cast(Any, SimpleNamespace()),
        dispatcher=dispatcher,
        redis_client=cast(Any, FakeStreamRedis(pubsub)),
        permission_service=cast(Any, SimpleNamespace()),
        feature_flag_service=_make_mock_feature_flag_service(),
    )
    workflow._merge_web_stream_metrics = AsyncMock()  # type: ignore[method-assign]

    with (
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.resolve_existing_generation_request",
            AsyncMock(return_value=None),
        ),
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.check_idempotency",
            AsyncMock(
                return_value=ChatIdempotencyState(
                    lock_key="lock:test",
                    lock_token="processing:test",
                    is_new=True,
                    value=None,
                )
            ),
        ),
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.prepare_request",
            AsyncMock(return_value=prepared),
        ),
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.queue_generation_request",
            AsyncMock(return_value=generation_attempt),
        ) as queue_request,
    ):
        stream = workflow.handle_query_stream(
            ChatQueryCommand(user_id=user_id, query_text="hello")
        )
        first_event = await anext(stream)
        queue_request.assert_awaited_once()
        dispatcher.enqueue_stream.assert_awaited_once()
        remaining_events = [event async for event in stream]

    assert first_event["type"] == "meta"
    assert remaining_events[-1]["type"] == "done"
    assert (
        dispatcher.enqueue_stream.await_args.kwargs["generation_attempt"]
        == generation_attempt
    )


async def test_dispatch_failure_reports_durable_recovery_pending() -> None:
    user_id = uuid.uuid4()
    session = SimpleNamespace(id=uuid.uuid4(), title="Session")
    assistant_message = SimpleNamespace(id=uuid.uuid4())
    generation_request = SimpleNamespace(
        id=uuid.uuid4(),
        attempt=1,
        status=ChatGenerationStatus.PREPARED,
    )
    prepared = ChatPreparedRequest(
        session=cast(Any, session),
        generation_request=cast(Any, generation_request),
        assistant_message=cast(Any, assistant_message),
        generation_payload=GenerationPayload(
            session_id=session.id,
            query_text="hello",
        ),
        lock_key=None,
        lock_token=None,
        trace_attrs={},
    )
    generation_attempt = GenerationAttemptPayload(
        request_id=generation_request.id,
        attempt=1,
        task_id="task-unavailable",
        lease_token="lease-unavailable",
    )
    dispatcher = AsyncMock()
    dispatcher.enqueue_stream.side_effect = ConnectionError("broker unavailable")
    workflow = ChatWorkflow(
        uow=cast(Any, SimpleNamespace()),
        dispatcher=dispatcher,
        redis_client=cast(Any, FakeStreamRedis(FakePubSub())),
        permission_service=cast(Any, SimpleNamespace()),
        feature_flag_service=_make_mock_feature_flag_service(),
    )

    async def queue_request(**_: object) -> GenerationAttemptPayload:
        generation_request.status = ChatGenerationStatus.QUEUED
        return generation_attempt

    with (
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.resolve_existing_generation_request",
            AsyncMock(return_value=None),
        ),
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.check_idempotency",
            AsyncMock(
                return_value=ChatIdempotencyState(
                    lock_key=None,
                    lock_token=None,
                    is_new=True,
                    value=None,
                )
            ),
        ),
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.prepare_request",
            AsyncMock(return_value=prepared),
        ),
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.queue_generation_request",
            AsyncMock(side_effect=queue_request),
        ) as queue_generation_request,
    ):
        events = [
            event
            async for event in workflow.handle_query_stream(
                ChatQueryCommand(user_id=user_id, query_text="hello")
            )
        ]

    queue_generation_request.assert_awaited_once()
    dispatcher.enqueue_stream.assert_awaited_once()
    assert generation_request.status == ChatGenerationStatus.QUEUED
    assert events[0]["type"] == "error"
    assert events[0]["error_code"] == "CHAT_DISPATCH_RECOVERY_PENDING"
    assert events[0]["retryable"] is False
    assert events[-1] == {"type": "done"}


async def test_retry_stream_uses_authorized_attempt_and_emits_identity() -> None:
    user_id = uuid.uuid4()
    request_id = uuid.uuid4()
    session = SimpleNamespace(id=uuid.uuid4(), title="Session")
    assistant_message = SimpleNamespace(id=uuid.uuid4())
    generation_request = SimpleNamespace(id=request_id, attempt=2)
    prepared = ChatPreparedRequest(
        session=cast(Any, session),
        generation_request=cast(Any, generation_request),
        assistant_message=cast(Any, assistant_message),
        generation_payload=GenerationPayload(
            session_id=session.id,
            query_text="retry",
        ),
        lock_key=None,
        lock_token=None,
        trace_attrs={},
    )
    generation_attempt = GenerationAttemptPayload(
        request_id=request_id,
        attempt=2,
        task_id="retry-task",
        lease_token="retry-lease",
    )
    dispatcher = AsyncMock()
    workflow = ChatWorkflow(
        uow=cast(Any, SimpleNamespace()),
        dispatcher=dispatcher,
        redis_client=cast(Any, FakeStreamRedis(FakePubSub())),
        permission_service=cast(Any, SimpleNamespace()),
        feature_flag_service=_make_mock_feature_flag_service(
            {"chat-explicit-retry": True}
        ),
    )
    workflow._merge_web_stream_metrics = AsyncMock()  # type: ignore[method-assign]

    with (
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.prepare_retry_request",
            AsyncMock(return_value=prepared),
        ) as prepare_retry,
        patch(
            "backend.application.chat.web_stream_workflow.ChatSessionOrchestrator.queue_generation_request",
            AsyncMock(return_value=generation_attempt),
        ),
    ):
        events = [
            event
            async for event in workflow.handle_retry_stream(
                command=RetryChatGenerationCommand(
                    user_id=user_id,
                    generation_request_id=request_id,
                    expected_attempt=1,
                ),
                user=cast(Any, SimpleNamespace(id=user_id)),
            )
        ]

    assert events[0] == {
        "type": "meta",
        "session_id": str(session.id),
        "session_title": "Session",
        "message_id": str(assistant_message.id),
        "generation_request_id": str(request_id),
        "attempt": 2,
    }
    assert events[-1] == {"type": "done"}
    prepare_retry.assert_awaited_once()
    dispatcher.enqueue_stream.assert_awaited_once()


def test_history_projection_keeps_only_user_and_assistant_messages() -> None:
    messages = [
        SimpleNamespace(role="system", content="ignore"),
        SimpleNamespace(role="user", content="hello"),
        {"role": "assistant", "content": "hi"},
        {"role": "assistant", "content": ""},
    ]

    assert history_to_conversation_messages(messages) == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


async def test_stream_workflow_merges_web_metrics_into_message_metadata() -> None:
    message = SimpleNamespace(
        status=MessageStatus.SUCCESS,
        message_metadata={"metrics": {"worker_total_latency_ms": 500}},
    )
    chat_repo = SimpleNamespace(
        get_message=AsyncMock(return_value=message),
        update_message_status=AsyncMock(),
    )
    uow = FakeUow(chat_repo)
    workflow = ChatWorkflow(
        uow=cast(Any, uow),
        dispatcher=cast(Any, SimpleNamespace()),
        redis_client=cast(Any, SimpleNamespace()),
        permission_service=cast(Any, SimpleNamespace()),
        feature_flag_service=_make_mock_feature_flag_service(),
    )

    await workflow._merge_web_stream_metrics(
        assistant_message_id=cast(Any, "message-id"),
        trace_attrs={},
        metrics={"queue_wait_ms": 10, "e2e_first_token_ms": 80},
    )

    update_kwargs = chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_metadata"]["metrics"] == {
        "worker_total_latency_ms": 500,
        "queue_wait_ms": 10,
        "e2e_first_token_ms": 80,
    }
