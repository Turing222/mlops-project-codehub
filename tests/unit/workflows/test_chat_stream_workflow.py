"""Chat stream workflow construction and history projection tests.

职责：验证 ChatWorkflow 轻量构造和 history_to_conversation_messages 的消息过滤；
边界：不启动 HTTP stack、不依赖 AI 服务；副作用：无。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from backend.application.chat.history_projection import history_to_conversation_messages
from backend.application.chat.web_stream_workflow import ChatWorkflow
from backend.models.enums import MessageStatus
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
    return svc


class FakeUow:
    def __init__(self, chat_repo: object) -> None:
        self.chat_repo = chat_repo

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def test_stream_workflow_constructs_without_ai_dependencies() -> None:
    workflow = ChatWorkflow(
        uow=cast(Any, SimpleNamespace()),
        dispatcher=cast(Any, SimpleNamespace()),
        redis_client=cast(Any, SimpleNamespace()),
        permission_service=cast(Any, SimpleNamespace()),
        feature_flag_service=_make_mock_feature_flag_service(),
    )

    assert workflow is not None


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


@pytest.mark.asyncio
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
