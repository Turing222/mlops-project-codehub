"""Task broker lifecycle unit tests.

职责：验证 worker 启停钩子中的依赖创建和 Redis 清理行为；边界：monkeypatch 替换 worker 依赖，不连接真实 Redis 或数据库；副作用：无。
"""

from unittest.mock import AsyncMock

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.requires_taskiq]


async def test_shutdown_cleans_up_redis_on_container_error_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.infra import task_broker
    from backend.infra.redis import redis_client
    from backend.worker import dependencies as worker_deps

    worker_deps.get_worker_container()

    async def mock_close_that_raises() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_deps, "close_worker_container", mock_close_that_raises)
    mock_redis_close = AsyncMock()
    monkeypatch.setattr(redis_client, "close", mock_redis_close)

    with pytest.raises(RuntimeError, match="boom"):
        await task_broker._shutdown_worker_dependencies(None)

    mock_redis_close.assert_awaited_once()


async def test_startup_creates_worker_container_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.infra import task_broker
    from backend.worker import dependencies as worker_deps

    worker_deps.set_worker_container(None)

    async def mock_close() -> None:
        pass

    monkeypatch.setattr(worker_deps.WorkerContainer, "close", mock_close)
    monkeypatch.setattr(
        worker_deps.WorkerContainer, "get_session_factory", lambda self: None
    )

    await task_broker._startup_worker_dependencies(None)

    container = worker_deps.get_worker_container()
    assert container is not None
