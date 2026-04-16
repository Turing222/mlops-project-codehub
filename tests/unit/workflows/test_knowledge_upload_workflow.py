from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from backend.models.orm.knowledge import FileStatus
from backend.workflow.knowledge_upload_workflow import KnowledgeUploadWorkflow


class DummyUoW:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_submit_stream_ingestion_creates_task_and_dispatches_job(monkeypatch):
    file_id = uuid.uuid4()
    task_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)

    knowledge_service = SimpleNamespace(
        uow=DummyUoW(),
        save_upload_file_streaming=AsyncMock(
            return_value=SimpleNamespace(
                id=file_id,
                file_path="/tmp/demo.txt",
                filename="demo.txt",
                status=FileStatus.UPLOADED,
            )
        ),
    )
    task_service = SimpleNamespace(
        uow=DummyUoW(),
        create_kb_ingestion_task=AsyncMock(
            return_value=SimpleNamespace(id=task_id, status="pending")
        ),
    )
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
    )

    kiq_mock = AsyncMock()
    monkeypatch.setattr(
        "backend.workflow.knowledge_upload_workflow.ingest_knowledge_file_task.kiq",
        kiq_mock,
    )

    result = await workflow.submit_stream_ingestion(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )

    knowledge_service.save_upload_file_streaming.assert_awaited_once_with(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )
    task_service.create_kb_ingestion_task.assert_awaited_once_with(
        kb_id=kb_id,
        file_id=file_id,
        file_path="/tmp/demo.txt",
        filename="demo.txt",
        user_id=user_id,
    )
    kiq_mock.assert_awaited_once_with(str(file_id), str(task_id))
    assert result.task_id == task_id
    assert result.file_id == file_id
    assert result.file_status == FileStatus.UPLOADED
    assert result.task_status == "pending"
