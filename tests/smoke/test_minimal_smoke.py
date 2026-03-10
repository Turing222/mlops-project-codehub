from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.workflow.chat_workflow import ChatWorkflow

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]


async def test_minimal_workflow_construction():
    uow = MagicMock()
    llm = AsyncMock()
    workflow = ChatWorkflow(uow, llm)

    assert workflow is not None
