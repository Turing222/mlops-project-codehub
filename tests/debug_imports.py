import asyncio
import os
import sys

sys.path.append(os.getcwd())

print("Testing imports...")
from backend.core.config import settings
print(f"Settings loaded: LLM_MAX_CONCURRENCY={settings.LLM_MAX_CONCURRENCY}")

from backend.workflow.chat_workflow import ChatWorkflow
print("ChatWorkflow imported.")

async def main():
    print("Initializing ChatWorkflow...")
    from unittest.mock import MagicMock
    uow = MagicMock()
    llm = MagicMock()
    wf = ChatWorkflow(uow, llm)
    print("ChatWorkflow initialized.")

if __name__ == "__main__":
    asyncio.run(main())
