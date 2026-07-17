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


class RecordingAsyncUow:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    async def __aenter__(self) -> RecordingAsyncUow:
        self.events.append(f"{self.name}.enter")
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        self.events.append(f"{self.name}.exit")


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


async def test_current_upload_commits_file_then_task_before_dispatch() -> None:
    """WS2 baseline: file and TaskJob commit separately before broker dispatch."""
    events: list[str] = []
    file_id = uuid.uuid4()
    task_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    file_obj = SimpleNamespace(
        id=file_id,
        file_path="/tmp/demo.md",
        filename="demo.md",
        status=FileStatus.UPLOADED,
    )

    async def save_file(**_: object) -> SavedKnowledgeFile:
        events.append("file.saved")
        return SavedKnowledgeFile(
            file=file_obj,
            should_ingest=True,
            deduplicated=False,
        )

    async def create_task(**_: object) -> SimpleNamespace:
        events.append("task.created")
        return SimpleNamespace(id=task_id, status="pending")

    async def dispatch(*_: object) -> None:
        events.append("broker.dispatch")

    knowledge_service = SimpleNamespace(
        uow=RecordingAsyncUow("knowledge_uow", events),
        save_upload_file_for_ingestion=AsyncMock(side_effect=save_file),
    )
    task_service = SimpleNamespace(
        uow=RecordingAsyncUow("task_uow", events),
        create_kb_ingestion_task=AsyncMock(side_effect=create_task),
    )
    dispatcher = SimpleNamespace(enqueue_ingestion=AsyncMock(side_effect=dispatch))
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=dispatcher,
    )

    await workflow.submit(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=MagicMock(spec=UploadFile),
    )

    assert events == [
        "knowledge_uow.enter",
        "file.saved",
        "knowledge_uow.exit",
        "task_uow.enter",
        "task.created",
        "task_uow.exit",
        "broker.dispatch",
    ]


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
