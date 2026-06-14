import asyncio


async def main() -> None:
    print("Testing imports...")

    from backend.application.chat.web_stream_workflow import ChatWorkflow
    from backend.config.settings import settings

    print("Initializing ChatWorkflow...")
    from unittest.mock import MagicMock

    print(f"Settings loaded: LLM_MAX_CONCURRENCY={settings.LLM_MAX_CONCURRENCY}")
    print("ChatWorkflow imported.")

    uow = MagicMock()
    dispatcher = MagicMock()
    redis_client = MagicMock()
    permission_service = MagicMock()
    ChatWorkflow(uow, dispatcher, redis_client, permission_service, MagicMock())
    print("ChatWorkflow initialized.")


if __name__ == "__main__":
    asyncio.run(main())
