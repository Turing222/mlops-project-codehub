"""Knowledge durable upload workflow tests.

职责：验证 File/TaskJob/TaskOutbox 单事务、commit 后快速发布、去重和回滚补偿。
边界：不连接真实数据库、对象存储或 Redis。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from backend.application.knowledge.outbox_relay import KnowledgeOutboxRelayService
from backend.application.knowledge.upload_workflow import KnowledgeUploadWorkflow
from backend.models.orm.knowledge import FileStatus
from backend.services.knowledge_service import SavedKnowledgeFile


class RecordingAsyncUow:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self) -> RecordingAsyncUow:
        self.events.append("uow.enter")
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.events.append("uow.rollback" if exc_type else "uow.commit")


class CommitUncertainUow(RecordingAsyncUow):
    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await super().__aexit__(exc_type, exc, traceback)
        if exc_type is None:
            raise ConnectionError("commit acknowledgement lost")


def _file(file_id: uuid.UUID, *, ready: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id,
        file_path="/tmp/demo.md",
        filename="demo.md",
        file_size=12,
        status=FileStatus.READY if ready else FileStatus.UPLOADED,
    )


async def test_upload_persists_file_task_and_outbox_in_one_uow_before_publish(
    monkeypatch,
) -> None:
    events: list[str] = []
    shared_uow = RecordingAsyncUow(events)
    file_id = uuid.uuid4()
    task_id = uuid.uuid4()
    outbox_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async def save_file(**_: object) -> SavedKnowledgeFile:
        events.append("file.created")
        return SavedKnowledgeFile(
            file=_file(file_id), should_ingest=True, deduplicated=False
        )

    async def create_task(**_: object) -> SimpleNamespace:
        events.append("task.created")
        return SimpleNamespace(id=task_id, status="pending")

    async def create_outbox(**_: object) -> SimpleNamespace:
        events.append("outbox.created")
        return SimpleNamespace(id=outbox_id)

    async def fast_publish(_self, *, outbox_id: uuid.UUID, now=None):
        events.append(f"outbox.published:{outbox_id}")
        return SimpleNamespace()

    monkeypatch.setattr(KnowledgeOutboxRelayService, "publish_one", fast_publish)
    knowledge_service = SimpleNamespace(
        uow=shared_uow,
        save_upload_file_for_ingestion=AsyncMock(side_effect=save_file),
        delete_stored_object=AsyncMock(),
    )
    task_service = SimpleNamespace(
        uow=shared_uow,
        create_kb_ingestion_task=AsyncMock(side_effect=create_task),
        create_kb_ingestion_outbox=AsyncMock(side_effect=create_outbox),
    )
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=SimpleNamespace(enqueue_ingestion=AsyncMock()),
    )

    result = await workflow.submit(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=MagicMock(spec=UploadFile),
    )

    assert events == [
        "uow.enter",
        "file.created",
        "task.created",
        "outbox.created",
        "uow.commit",
        f"outbox.published:{outbox_id}",
    ]
    task_service.create_kb_ingestion_outbox.assert_awaited_once()
    assert result.task_id == task_id
    assert result.file_id == file_id
    assert result.task_status == "pending"


async def test_upload_rollback_discards_new_object_without_broker_publish(
    monkeypatch,
) -> None:
    shared_uow = RecordingAsyncUow([])
    file_obj = _file(uuid.uuid4())
    publish = AsyncMock()
    monkeypatch.setattr(KnowledgeOutboxRelayService, "publish_one", publish)
    knowledge_service = SimpleNamespace(
        uow=shared_uow,
        save_upload_file_for_ingestion=AsyncMock(
            return_value=SavedKnowledgeFile(
                file=file_obj,
                should_ingest=True,
                deduplicated=False,
            )
        ),
        delete_stored_object=AsyncMock(),
    )
    task_service = SimpleNamespace(
        uow=shared_uow,
        create_kb_ingestion_task=AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4(), status="pending")
        ),
        create_kb_ingestion_outbox=AsyncMock(side_effect=RuntimeError("db gone")),
    )
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=SimpleNamespace(enqueue_ingestion=AsyncMock()),
    )

    with pytest.raises(RuntimeError, match="db gone"):
        await workflow.submit(
            kb_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            upload_file=MagicMock(spec=UploadFile),
        )

    knowledge_service.delete_stored_object.assert_awaited_once_with(file_obj=file_obj)
    publish.assert_not_awaited()


async def test_uncertain_commit_preserves_object_and_skips_fast_publish(
    monkeypatch,
) -> None:
    shared_uow = CommitUncertainUow([])
    file_obj = _file(uuid.uuid4())
    publish = AsyncMock()
    monkeypatch.setattr(KnowledgeOutboxRelayService, "publish_one", publish)
    knowledge_service = SimpleNamespace(
        uow=shared_uow,
        save_upload_file_for_ingestion=AsyncMock(
            return_value=SavedKnowledgeFile(
                file=file_obj,
                should_ingest=True,
                deduplicated=False,
            )
        ),
        delete_stored_object=AsyncMock(),
    )
    task_service = SimpleNamespace(
        uow=shared_uow,
        create_kb_ingestion_task=AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4(), status="pending")
        ),
        create_kb_ingestion_outbox=AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4())
        ),
    )
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=SimpleNamespace(enqueue_ingestion=AsyncMock()),
    )

    with pytest.raises(ConnectionError, match="acknowledgement lost"):
        await workflow.submit(
            kb_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            upload_file=MagicMock(spec=UploadFile),
        )

    knowledge_service.delete_stored_object.assert_not_awaited()
    publish.assert_not_awaited()


async def test_ready_duplicate_creates_completed_task_without_outbox(
    monkeypatch,
) -> None:
    shared_uow = RecordingAsyncUow([])
    task_id = uuid.uuid4()
    file_obj = _file(uuid.uuid4(), ready=True)
    publish = AsyncMock()
    monkeypatch.setattr(KnowledgeOutboxRelayService, "publish_one", publish)
    knowledge_service = SimpleNamespace(
        uow=shared_uow,
        save_upload_file_for_ingestion=AsyncMock(
            return_value=SavedKnowledgeFile(
                file=file_obj,
                should_ingest=False,
                deduplicated=True,
            )
        ),
        delete_stored_object=AsyncMock(),
    )
    task_service = SimpleNamespace(
        uow=shared_uow,
        create_completed_kb_ingestion_task=AsyncMock(
            return_value=SimpleNamespace(id=task_id, status="completed")
        ),
        create_kb_ingestion_outbox=AsyncMock(),
    )
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=SimpleNamespace(enqueue_ingestion=AsyncMock()),
    )

    result = await workflow.submit(
        kb_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        upload_file=MagicMock(spec=UploadFile),
    )

    task_service.create_kb_ingestion_outbox.assert_not_awaited()
    publish.assert_not_awaited()
    assert result.deduplicated is True
    assert result.task_status == "completed"


async def test_default_kb_is_resolved_inside_the_shared_transaction(
    monkeypatch,
) -> None:
    events: list[str] = []
    shared_uow = RecordingAsyncUow(events)
    kb_id = uuid.uuid4()
    outbox_id = uuid.uuid4()
    monkeypatch.setattr(
        KnowledgeOutboxRelayService,
        "publish_one",
        AsyncMock(return_value=SimpleNamespace()),
    )
    knowledge_service = SimpleNamespace(
        uow=shared_uow,
        get_or_create_default_kb=AsyncMock(return_value=SimpleNamespace(id=kb_id)),
        save_upload_file_for_ingestion=AsyncMock(
            return_value=SavedKnowledgeFile(
                file=_file(uuid.uuid4()),
                should_ingest=True,
                deduplicated=False,
            )
        ),
        delete_stored_object=AsyncMock(),
    )
    task_service = SimpleNamespace(
        uow=shared_uow,
        create_kb_ingestion_task=AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4(), status="pending")
        ),
        create_kb_ingestion_outbox=AsyncMock(
            return_value=SimpleNamespace(id=outbox_id)
        ),
    )
    workflow = KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=SimpleNamespace(enqueue_ingestion=AsyncMock()),
    )

    result = await workflow.submit(
        user_id=uuid.uuid4(),
        upload_file=MagicMock(spec=UploadFile),
    )

    knowledge_service.get_or_create_default_kb.assert_awaited_once()
    assert result.kb_id == kb_id
