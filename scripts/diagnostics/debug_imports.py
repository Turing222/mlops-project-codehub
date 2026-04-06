import asyncio


async def main() -> None:
    print("Testing imports...")

    from backend.core.config import settings
    from backend.workflow.chat_workflow import ChatWorkflow

    print("Initializing ChatWorkflow...")
    from unittest.mock import MagicMock

    print(f"Settings loaded: LLM_MAX_CONCURRENCY={settings.LLM_MAX_CONCURRENCY}")
    print("ChatWorkflow imported.")

    uow = MagicMock()
    llm = MagicMock()
    ChatWorkflow(uow, llm)
    print("ChatWorkflow initialized.")


if __name__ == "__main__":
    asyncio.run(main())
