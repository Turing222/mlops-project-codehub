"""Workflow concurrency performance tests.

职责：工作流并发性能基准；边界：performance marker；副作用：无。
"""

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.application.chat.web_stream_workflow import ChatWorkflow
from backend.core.concurrency import reset_semaphores
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.models.schemas.chat.context_state import ContextState
from backend.services.feature_flag_service import (
    _AI_SYSTEM_FLAG_DEFAULTS,
    FeatureFlagService,
)

pytestmark = pytest.mark.performance


class _FakePubSub:
    async def subscribe(self, _channel: str) -> None:
        return None

    async def unsubscribe(self, _channel: str) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def listen(self):
        yield {"type": "message", "data": '{"type":"started"}'}
        yield {"type": "message", "data": '{"type":"chunk","content":"ok"}'}
        yield {"type": "message", "data": '{"type":"done"}'}


class _FakeRedis:
    def pubsub(self) -> _FakePubSub:
        return _FakePubSub()


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


async def test_workflow_concurrency():
    with (
        patch(
            "backend.application.chat.web_stream_workflow.settings.LLM_MAX_CONCURRENCY",
            2,
        ),
        patch(
            "backend.application.chat.web_stream_workflow.settings.DB_MAX_CONCURRENCY",
            2,
        ),
    ):
        reset_semaphores()

        uow = MagicMock()
        uow.__aenter__.return_value = uow
        uow.__aexit__.return_value = None
        uow.user_repo = AsyncMock()
        uow.user_repo.get_with_lock = AsyncMock(
            return_value=MagicMock(max_tokens=100_000, used_tokens=0)
        )
        uow.credit_repo = AsyncMock()
        uow.credit_repo.get_account_with_lock = AsyncMock(
            return_value=MagicMock(id=uuid.uuid4(), balance=10_000)
        )
        uow.credit_repo.create_account = AsyncMock()
        uow.chat_repo = AsyncMock()
        uow.chat_repo.get_context_state = AsyncMock(return_value=ContextState())
        uow.chat_repo.get_message = AsyncMock(return_value=None)

        dispatcher = AsyncMock()

        with (
            patch(
                "backend.application.chat.web_stream_workflow.SessionManager"
            ) as mock_sm,
            patch(
                "backend.application.chat.web_stream_workflow.ChatMessageUpdater"
            ) as mock_up,
        ):
            mock_sm_inst = mock_sm.return_value

            async def ensure_session_with_db_delay(**_kwargs):
                await asyncio.sleep(0.5)
                return MagicMock(id=uuid.uuid4(), title="test", kb_id=None)

            mock_sm_inst.ensure_session = AsyncMock(
                side_effect=ensure_session_with_db_delay
            )
            mock_sm_inst.create_user_message = AsyncMock()
            mock_sm_inst.create_assistant_message = AsyncMock(
                return_value=MagicMock(id=uuid.uuid4())
            )
            mock_sm_inst.get_session_messages = AsyncMock(return_value=[])

            mock_up_inst = mock_up.return_value
            mock_up_inst.update_as_success = AsyncMock()
            mock_up_inst.update_as_failed = AsyncMock()

            workflow = ChatWorkflow(
                uow=uow,
                dispatcher=dispatcher,
                redis_client=_FakeRedis(),
                permission_service=MagicMock(),
                feature_flag_service=_make_mock_feature_flag_service(),
            )

            user_id = uuid.uuid4()
            start_time = time.time()

            async def consume_stream():
                events = []
                async for event in workflow.handle_query_stream(
                    ChatQueryCommand(
                        user_id=user_id,
                        query_text="hello",
                    )
                ):
                    events.append(event)
                return events

            tasks = [consume_stream() for _ in range(4)]
            results = await asyncio.gather(*tasks)

            end_time = time.time()
            total_time = end_time - start_time
            assert 0.9 <= total_time <= 1.5
            assert dispatcher.enqueue_stream.await_count == 4
            for events in results:
                assert any(event["type"] == "chunk" for event in events)
                assert events[-1]["type"] == "done"

    reset_semaphores()
