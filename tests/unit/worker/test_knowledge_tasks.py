"""Knowledge TaskIQ task unit tests.

职责：验证知识库 worker task 的失败回写保护；边界：不启动 TaskIQ worker、不连接真实数据库；
副作用：无。
"""

import uuid
from unittest.mock import AsyncMock

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.requires_taskiq]


async def test_safe_mark_failed_swallows_mark_failed_error() -> None:
    from backend.worker.tasks.knowledge_tasks import safe_mark_failed

    task_id = uuid.uuid4()
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    task_service = AsyncMock()
    task_service.mark_failed = AsyncMock(side_effect=RuntimeError("db gone"))

    await safe_mark_failed(
        uow=uow,
        task_service=task_service,
        task_id=task_id,
        error_log="知识文件处理失败，请稍后重试",
    )

    task_service.mark_failed.assert_awaited_once_with(
        task_id=task_id,
        error_log="知识文件处理失败，请稍后重试",
    )


async def test_safe_mark_failed_skips_none_task_id() -> None:
    from backend.worker.tasks.knowledge_tasks import safe_mark_failed

    uow = AsyncMock()
    task_service = AsyncMock()

    await safe_mark_failed(
        uow=uow,
        task_service=task_service,
        task_id=None,
        error_log="ignored",
    )

    task_service.mark_failed.assert_not_awaited()
