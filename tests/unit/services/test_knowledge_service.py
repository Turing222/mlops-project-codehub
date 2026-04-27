from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from backend.core.exceptions import ResourceNotFound, ValidationError
from backend.models.orm.knowledge import FileStatus
from backend.services.knowledge_service import KnowledgeService


@pytest.fixture
def knowledge_service(tmp_path: Path):
    repo = SimpleNamespace(
        get_kb_by_name_for_user=AsyncMock(),
        get_kb_for_user=AsyncMock(),
        create_kb=AsyncMock(),
        create_file=AsyncMock(),
    )
    uow = SimpleNamespace(knowledge_repo=repo)
    service = KnowledgeService(uow=uow, storage_root=tmp_path, max_upload_size_mb=1)
    return service, repo, tmp_path


def make_upload_file(
    filename: str, content: bytes, *, size: int | None = None
) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        size=size,
    )


class TestKnowledgeServiceStreamingUpload:
    @pytest.mark.asyncio
    async def test_save_upload_file_streaming_writes_file_and_records_metadata(
        self,
        knowledge_service,
    ):
        service, repo, storage_root = knowledge_service
        kb_id = uuid.uuid4()
        user_id = uuid.uuid4()
        workspace_id = uuid.uuid4()
        content = b"streaming upload content"

        repo.get_kb_for_user.return_value = SimpleNamespace(
            id=kb_id,
            workspace_id=workspace_id,
        )

        async def create_file(**kwargs):
            return SimpleNamespace(id=uuid.uuid4(), **kwargs)

        repo.create_file.side_effect = create_file
        upload_file = make_upload_file("demo.txt", content, size=len(content))

        result = await service.save_upload_file_streaming(
            kb_id=kb_id,
            user_id=user_id,
            upload_file=upload_file,
        )

        saved_path = Path(result.file_path)
        assert saved_path.exists()
        assert saved_path.read_bytes() == content
        assert saved_path.parent == storage_root / str(kb_id)
        assert result.filename == "demo.txt"
        assert result.file_size == len(content)
        assert result.status == FileStatus.UPLOADED
        assert result.owner_id == user_id
        assert result.workspace_id == workspace_id
        repo.get_kb_for_user.assert_awaited_once_with(kb_id=kb_id, user_id=user_id)
        repo.create_file.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_upload_file_streaming_rejects_missing_kb_access(
        self,
        knowledge_service,
    ):
        service, repo, storage_root = knowledge_service

        repo.get_kb_for_user.return_value = None
        upload_file = make_upload_file("demo.txt", b"abc", size=3)

        with pytest.raises(ResourceNotFound):
            await service.save_upload_file_streaming(
                kb_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                upload_file=upload_file,
            )

        repo.create_file.assert_not_awaited()
        assert not any(path.is_file() for path in storage_root.rglob("*"))

    @pytest.mark.asyncio
    async def test_save_upload_file_streaming_cleans_partial_file_when_size_limit_exceeded(
        self,
        knowledge_service,
    ):
        service, repo, storage_root = knowledge_service
        kb_id = uuid.uuid4()
        user_id = uuid.uuid4()

        repo.get_kb_for_user.return_value = SimpleNamespace(id=kb_id)
        oversize_content = b"a" * (service.max_upload_size_bytes + 128)
        upload_file = make_upload_file("too-large.txt", oversize_content)

        with pytest.raises(ValidationError) as exc_info:
            await service.save_upload_file_streaming(
                kb_id=kb_id,
                user_id=user_id,
                upload_file=upload_file,
            )

        assert f"最大 {service.max_upload_size_mb}MB" in exc_info.value.message
        repo.create_file.assert_not_awaited()
        assert not any(path.is_file() for path in storage_root.rglob("*"))


class TestKnowledgeServiceDefaultKnowledgeBase:
    @pytest.mark.asyncio
    async def test_get_or_create_default_kb_returns_existing_kb(
        self, knowledge_service
    ):
        service, repo, _ = knowledge_service
        user_id = uuid.uuid4()
        existing_kb = SimpleNamespace(id=uuid.uuid4(), user_id=user_id)
        repo.get_kb_by_name_for_user.return_value = existing_kb

        result = await service.get_or_create_default_kb(user_id=user_id)

        assert result == existing_kb
        repo.get_kb_by_name_for_user.assert_awaited_once()
        repo.create_kb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_or_create_default_kb_creates_missing_kb(self, knowledge_service):
        service, repo, _ = knowledge_service
        user_id = uuid.uuid4()
        created_kb = SimpleNamespace(id=uuid.uuid4(), user_id=user_id)
        repo.get_kb_by_name_for_user.return_value = None
        repo.create_kb.return_value = created_kb

        result = await service.get_or_create_default_kb(user_id=user_id)

        assert result == created_kb
        repo.create_kb.assert_awaited_once_with(
            name="默认知识库",
            description="系统自动创建的默认知识库",
            user_id=user_id,
        )
