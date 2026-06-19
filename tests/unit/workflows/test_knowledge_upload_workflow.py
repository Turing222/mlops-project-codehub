"""Knowledge upload workflow tests — file submission, deduplication, and task dispatch.

职责：验证 KnowledgeUploadWorkflow 的文件提交（显式/默认 kb）、去重重用和任务派发；
边界：不启动 HTTP stack、不连接真实数据库或 Redis；副作用：无。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

from fastapi import UploadFile

from backend.application.knowledge.upload_workflow import KnowledgeUploadWorkflow
from backend.models.orm.knowledge import FileStatus
from backend.services.knowledge_service import SavedKnowledgeFile
from tests.unit.workflows.conftest import FakeAsyncUow


async def test_submit_with_explicit_kb_creates_task_and_dispatches_job(
    monkeypatch,
) -> None:
    file_id = uuid.uuid4()
    task_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)

    knowledge_service = SimpleNamespace(
        uow=FakeAsyncUow(),
        save_upload_file_for_ingestion=AsyncMock(
            return_value=SavedKnowledgeFile(
                file=SimpleNamespace(
                    id=file_id,
                    file_path="/tmp/demo.md",
                    filename="demo.md",
                    status=FileStatus.UPLOADED,
                ),
                should_ingest=True,
                deduplicated=False,
            )
        ),
    )
    task_service = SimpleNamespace(
        uow=FakeAsyncUow(),
        create_kb_ingestion_task=AsyncMock(
            return_value=SimpleNamespace(id=task_id, status="pending")
        ),
    )
    mock_dispatcher = SimpleNamespace(enqueue_ingestion=AsyncMock())
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=mock_dispatcher,
    )

    result = await workflow.submit(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )

    knowledge_service.save_upload_file_for_ingestion.assert_awaited_once_with(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )
    task_service.create_kb_ingestion_task.assert_awaited_once_with(
        kb_id=kb_id,
        file_id=file_id,
        file_path="/tmp/demo.md",
        filename="demo.md",
        user_id=user_id,
    )
    mock_dispatcher.enqueue_ingestion.assert_awaited_once_with(
        str(file_id), str(task_id), ANY
    )
    assert result.task_id == task_id
    assert result.file_id == file_id
    assert result.kb_id == kb_id
    assert result.file_status == FileStatus.UPLOADED
    assert result.task_status == "pending"
    assert result.deduplicated is False


async def test_submit_reuses_ready_duplicate_without_dispatching_job() -> None:
    file_id = uuid.uuid4()
    task_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)

    knowledge_service = SimpleNamespace(
        uow=FakeAsyncUow(),
        save_upload_file_for_ingestion=AsyncMock(
            return_value=SavedKnowledgeFile(
                file=SimpleNamespace(
                    id=file_id,
                    file_path="/tmp/existing.md",
                    filename="existing.md",
                    status=FileStatus.READY,
                ),
                should_ingest=False,
                deduplicated=True,
            )
        ),
    )
    task_service = SimpleNamespace(
        uow=FakeAsyncUow(),
        create_completed_kb_ingestion_task=AsyncMock(
            return_value=SimpleNamespace(id=task_id, status="completed")
        ),
    )
    mock_dispatcher = SimpleNamespace(enqueue_ingestion=AsyncMock())
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=mock_dispatcher,
    )

    result = await workflow.submit(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )

    task_service.create_completed_kb_ingestion_task.assert_awaited_once_with(
        kb_id=kb_id,
        file_id=file_id,
        file_path="/tmp/existing.md",
        filename="existing.md",
        user_id=user_id,
        deduplicated=True,
    )
    mock_dispatcher.enqueue_ingestion.assert_not_awaited()
    assert result.file_id == file_id
    assert result.task_id == task_id
    assert result.task_status == "completed"
    assert result.file_status == FileStatus.READY
    assert result.deduplicated is True


async def test_submit_without_kb_id_uses_default_kb_and_dispatches_job() -> None:
    file_id = uuid.uuid4()
    task_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)

    knowledge_service = SimpleNamespace(
        uow=FakeAsyncUow(),
        get_or_create_default_kb=AsyncMock(return_value=SimpleNamespace(id=kb_id)),
        save_upload_file_for_ingestion=AsyncMock(
            return_value=SavedKnowledgeFile(
                file=SimpleNamespace(
                    id=file_id,
                    file_path="/tmp/demo.md",
                    filename="demo.md",
                    status=FileStatus.UPLOADED,
                ),
                should_ingest=True,
                deduplicated=False,
            )
        ),
    )
    task_service = SimpleNamespace(
        uow=FakeAsyncUow(),
        create_kb_ingestion_task=AsyncMock(
            return_value=SimpleNamespace(id=task_id, status="pending")
        ),
    )
    mock_dispatcher = SimpleNamespace(enqueue_ingestion=AsyncMock())
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=mock_dispatcher,
    )

    result = await workflow.submit(
        user_id=user_id,
        upload_file=upload_file,
    )

    knowledge_service.get_or_create_default_kb.assert_awaited_once_with(user_id=user_id)
    knowledge_service.save_upload_file_for_ingestion.assert_awaited_once_with(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )
    task_service.create_kb_ingestion_task.assert_awaited_once_with(
        kb_id=kb_id,
        file_id=file_id,
        file_path="/tmp/demo.md",
        filename="demo.md",
        user_id=user_id,
    )
    mock_dispatcher.enqueue_ingestion.assert_awaited_once_with(
        str(file_id), str(task_id), ANY
    )
    assert result.task_id == task_id
    assert result.file_id == file_id
    assert result.kb_id == kb_id
    assert result.file_status == FileStatus.UPLOADED
    assert result.task_status == "pending"
    assert result.deduplicated is False
