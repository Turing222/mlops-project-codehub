import asyncio
import time
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.workflow.chat_workflow import ChatWorkflow

pytestmark = [pytest.mark.asyncio, pytest.mark.performance]


async def test_workflow_concurrency():
    with patch("backend.workflow.chat_workflow.settings.LLM_MAX_CONCURRENCY", 2), \
         patch("backend.workflow.chat_workflow.settings.DB_MAX_CONCURRENCY", 2):
        ChatWorkflow._llm_semaphore = asyncio.Semaphore(2)
        ChatWorkflow._db_semaphore = asyncio.Semaphore(2)

        uow = MagicMock()
        uow.__aenter__.return_value = uow
        uow.__aexit__.return_value = None

        llm_service = MagicMock()

        async def mock_stream(*args, **kwargs):
            await asyncio.sleep(0.5)
            yield '{"type":"chunk", "content":"hello"}'

        llm_service.stream_response = MagicMock(side_effect=mock_stream)

        with patch("backend.workflow.chat_workflow.SessionManager") as mock_sm, \
             patch("backend.workflow.chat_workflow.ChatMessageUpdater") as mock_up, \
             patch("backend.workflow.chat_workflow.PromptManager") as mock_pm:
            mock_sm_inst = mock_sm.return_value
            mock_sm_inst.ensure_session = AsyncMock(return_value=MagicMock(id=uuid.uuid4(), title="test"))
            mock_sm_inst.create_user_message = AsyncMock()
            mock_sm_inst.create_assistant_message = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            mock_sm_inst.get_session_messages = AsyncMock(return_value=[])

            mock_up_inst = mock_up.return_value
            mock_up_inst.update_as_success = AsyncMock()
            mock_up_inst.update_as_failed = AsyncMock()

            mock_pm_inst = mock_pm.return_value
            mock_pm_inst.assemble = MagicMock(return_value=MagicMock(messages=[], total_tokens=0, history_rounds_used=0, truncated=False))

            workflow = ChatWorkflow(uow, llm_service)

            user_id = uuid.uuid4()
            start_time = time.time()

            async def consume_stream():
                async for _ in workflow.handle_query_stream(user_id=user_id, query_text="hello"):
                    pass

            tasks = [consume_stream() for _ in range(4)]
            await asyncio.gather(*tasks)

            end_time = time.time()
            total_time = end_time - start_time
            assert 0.9 <= total_time <= 1.5
