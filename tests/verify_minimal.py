import asyncio
import uuid
import sys
import os
from unittest.mock import AsyncMock, patch, MagicMock

# 设置 PYTHONPATH
sys.path.append(os.getcwd())

print("Pre-importing ChatWorkflow...")
from backend.workflow.chat_workflow import ChatWorkflow
print("ChatWorkflow imported.")

async def test_minimal():
    print("Minimal test running...")
    uow = MagicMock()
    llm = AsyncMock()
    wf = ChatWorkflow(uow, llm)
    print("Test passed!")

if __name__ == "__main__":
    asyncio.run(test_minimal())
