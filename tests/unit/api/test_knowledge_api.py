"""Knowledge API unit tests.

职责：验证 endpoint 对上传 workflow 的参数传递和响应返回；边界：直接调用 endpoint 函数，不启动 FastAPI app 或真实存储；副作用：无。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from backend.api.v1.endpoint import knowledge_api
from backend.models.schemas.knowledge_schema import KnowledgeUploadResponse

pytestmark = pytest.mark.asyncio


async def test_upload_file_delegates_to_submit_workflow() -> None:
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)
    expected = KnowledgeUploadResponse(
        task_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        kb_id=kb_id,
        file_status="uploaded",
        task_status="pending",
    )
    upload_workflow = SimpleNamespace(submit=AsyncMock(return_value=expected))

    result = await knowledge_api.upload_file(
        kb_id=kb_id,
        file=upload_file,
        current_user=SimpleNamespace(id=user_id),
        upload_workflow=upload_workflow,
        audit_service=SimpleNamespace(),
    )

    assert result == expected
    upload_workflow.submit.assert_awaited_once_with(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )


async def test_upload_file_to_default_kb_delegates_to_submit_workflow() -> None:
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)
    expected = KnowledgeUploadResponse(
        task_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        file_status="uploaded",
        task_status="pending",
    )
    upload_workflow = SimpleNamespace(submit=AsyncMock(return_value=expected))

    result = await knowledge_api.upload_file_to_default_kb(
        file=upload_file,
        current_user=SimpleNamespace(id=user_id),
        upload_workflow=upload_workflow,
        audit_service=SimpleNamespace(),
    )

    assert result == expected
    upload_workflow.submit.assert_awaited_once_with(
        user_id=user_id,
        upload_file=upload_file,
    )


class AsyncContextManagerMock:
    async def __aenter__(self) -> None:
        pass

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        pass


async def test_get_default_kb_files_success() -> None:
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    kb = SimpleNamespace(id=kb_id)
    files = [
        SimpleNamespace(
            id=uuid.uuid4(),
            kb_id=kb_id,
            filename="file.md",
            file_size=100,
            content_sha256="sha",
            status="ready",
            created_at="2026-05-23T12:00:00",
            updated_at="2026-05-23T12:00:00",
        )
    ]
    service = AsyncMock()
    service.read = MagicMock(return_value=AsyncContextManagerMock())
    service.write = MagicMock(return_value=AsyncContextManagerMock())
    service.get_default_kb_for_user = AsyncMock(return_value=kb)
    service.get_or_create_default_kb = AsyncMock(return_value=kb)
    service.list_files_by_kb_id = AsyncMock(return_value=files)

    result = await knowledge_api.get_default_kb_files(
        current_user=SimpleNamespace(id=user_id),
        service=service,
    )
    assert len(result) == 1
    assert result[0].filename == "file.md"
    service.get_default_kb_for_user.assert_awaited_once_with(user_id=user_id)
    service.list_files_by_kb_id.assert_awaited_once_with(kb_id=kb_id, user_id=user_id)


async def test_delete_kb_file_success() -> None:
    file_id = uuid.uuid4()
    user_id = uuid.uuid4()
    service = AsyncMock()
    service.write = MagicMock(return_value=AsyncContextManagerMock())
    service.remove_file = AsyncMock()

    await knowledge_api.delete_kb_file(
        file_id=file_id,
        current_user=SimpleNamespace(id=user_id),
        service=service,
        audit_service=SimpleNamespace(),
    )
    service.remove_file.assert_awaited_once_with(file_id=file_id, user_id=user_id)
