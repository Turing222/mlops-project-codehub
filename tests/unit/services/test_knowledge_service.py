"""Knowledge service unit tests.

职责：验证 KnowledgeService 的文件上传、去重重用和默认知识库创建行为；边界：使用 tmp_path 和 SimpleNamespace mock，不连接真实数据库或对象存储；副作用：无。
"""

from __future__ import annotations

import hashlib
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from backend.core.exceptions import AppException
from backend.models.orm.knowledge import FileStatus
from backend.services.knowledge_service import KnowledgeService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def knowledge_service(tmp_path: Path) -> tuple[KnowledgeService, SimpleNamespace, Path]:
    repo = SimpleNamespace(
        get_kb_by_name_for_user=AsyncMock(),
        get_kb_for_user=AsyncMock(),
        get_kb=AsyncMock(return_value=None),
        get_file_by_hash_and_status=AsyncMock(return_value=None),
        create_kb=AsyncMock(),
        create_file=AsyncMock(),
    )
    uow = SimpleNamespace(knowledge_repo=repo)
    permission_service = SimpleNamespace(
        has_permission_for_user_id=AsyncMock(return_value=True)
    )
    service = KnowledgeService(
        uow=uow,
        storage_root=tmp_path,
        max_upload_size_mb=1,
        permission_service=permission_service,
    )
    return service, repo, tmp_path


def make_upload_file(
    filename: str, content: bytes, *, size: int | None = None
) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        size=size,
    )


async def test_save_upload_file_writes_file_and_records_metadata_returns_record(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, storage_root = knowledge_service
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    content = b"streaming upload content"

    repo.get_kb_for_user.return_value = SimpleNamespace(
        id=kb_id,
        workspace_id=workspace_id,
    )

    async def create_file(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(id=uuid.uuid4(), **kwargs)

    repo.create_file.side_effect = create_file
    upload_file = make_upload_file("demo.md", content, size=len(content))

    result = await service.save_upload_file(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )

    saved_path = Path(result.file_path)
    assert saved_path.exists()
    assert saved_path.read_bytes() == content
    assert result.storage_key.startswith(
        f"v1/knowledge/workspaces/{workspace_id}/kb/{kb_id}/files/"
    )
    assert saved_path == storage_root / result.storage_key
    assert result.filename == "demo.md"
    assert result.file_size == len(content)
    assert result.content_sha256 == hashlib.sha256(content).hexdigest()
    assert result.status == FileStatus.UPLOADED
    assert result.owner_id == user_id
    assert result.workspace_id == workspace_id
    repo.get_kb_for_user.assert_awaited_once_with(kb_id=kb_id, user_id=user_id)
    repo.get_file_by_hash_and_status.assert_awaited_once_with(
        kb_id=kb_id,
        content_sha256=hashlib.sha256(content).hexdigest(),
        status=FileStatus.READY,
    )
    repo.create_file.assert_awaited_once()


async def test_save_upload_file_reuses_ready_duplicate_deletes_new_object(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, storage_root = knowledge_service
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    content = b"duplicate content"
    duplicate = SimpleNamespace(
        id=uuid.uuid4(),
        kb_id=kb_id,
        filename="existing.md",
        file_path="/already/indexed.md",
        file_size=len(content),
        content_sha256=hashlib.sha256(content).hexdigest(),
        status=FileStatus.READY,
    )
    repo.get_kb_for_user.return_value = SimpleNamespace(
        id=kb_id,
        workspace_id=None,
        user_id=user_id,
    )
    repo.get_file_by_hash_and_status.return_value = duplicate

    result = await service.save_upload_file(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=make_upload_file("demo.md", content, size=len(content)),
    )

    assert result == duplicate
    repo.create_file.assert_not_awaited()
    assert not any(path.is_file() for path in storage_root.rglob("*"))


async def test_save_upload_file_rejects_missing_kb_access(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, storage_root = knowledge_service

    repo.get_kb_for_user.return_value = None
    upload_file = make_upload_file("demo.md", b"abc", size=3)

    with pytest.raises(AppException):
        await service.save_upload_file(
            kb_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            upload_file=upload_file,
        )

    repo.create_file.assert_not_awaited()
    assert not any(path.is_file() for path in storage_root.rglob("*"))


async def test_save_upload_file_rejects_non_markdown_file(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, storage_root = knowledge_service
    upload_file = make_upload_file("demo.txt", b"abc", size=3)

    with pytest.raises(AppException) as exc_info:
        await service.save_upload_file(
            kb_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            upload_file=upload_file,
        )

    assert exc_info.value.code == "KNOWLEDGE_FILE_UNSUPPORTED_TYPE"
    repo.get_kb_for_user.assert_not_awaited()
    repo.create_file.assert_not_awaited()
    assert not any(path.is_file() for path in storage_root.rglob("*"))


async def test_save_upload_file_cleans_partial_file_when_size_limit_exceeded(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, storage_root = knowledge_service
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    repo.get_kb_for_user.return_value = SimpleNamespace(
        id=kb_id,
        workspace_id=None,
        user_id=user_id,
    )
    oversize_content = b"a" * (service.max_upload_size_bytes + 128)
    upload_file = make_upload_file("too-large.md", oversize_content)

    with pytest.raises(AppException) as exc_info:
        await service.save_upload_file(
            kb_id=kb_id,
            user_id=user_id,
            upload_file=upload_file,
        )

    assert f"最大 {service.max_upload_size_mb}MB" in exc_info.value.message
    repo.create_file.assert_not_awaited()
    assert not any(path.is_file() for path in storage_root.rglob("*"))


async def test_get_or_create_default_kb_returns_existing_kb(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, _ = knowledge_service
    user_id = uuid.uuid4()
    existing_kb = SimpleNamespace(id=uuid.uuid4(), user_id=user_id)
    repo.get_kb_by_name_for_user.return_value = existing_kb

    result = await service.get_or_create_default_kb(user_id=user_id)

    assert result == existing_kb
    repo.get_kb_by_name_for_user.assert_awaited_once()
    repo.create_kb.assert_not_awaited()


async def test_get_or_create_default_kb_creates_missing_kb(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
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


async def test_list_files_by_kb_id_returns_files(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, _ = knowledge_service
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    files = [SimpleNamespace(id=uuid.uuid4(), filename="file1.md")]
    repo.get_kb_for_user.return_value = SimpleNamespace(
        id=kb_id, user_id=user_id, workspace_id=None
    )
    repo.list_files_by_kb = AsyncMock(return_value=files)

    result = await service.list_files_by_kb_id(kb_id=kb_id, user_id=user_id)
    assert result == files
    repo.list_files_by_kb.assert_awaited_once_with(kb_id)


async def test_remove_file_success(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, _ = knowledge_service
    file_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    file_obj = SimpleNamespace(
        id=file_id,
        kb_id=kb_id,
        filename="test.md",
        file_path="mock_path",
        file_size=10,
        content_sha256="sha256",
        storage_backend="local",
        storage_bucket=None,
        storage_key="test_key",
    )
    repo.get_file = AsyncMock(return_value=file_obj)
    repo.get_kb_for_user.return_value = SimpleNamespace(
        id=kb_id, user_id=user_id, workspace_id=None
    )
    repo.delete_chunks_for_file = AsyncMock()
    repo.delete_file_record = AsyncMock()

    service.storage.delete = AsyncMock()

    await service.remove_file(file_id=file_id, user_id=user_id)

    repo.get_file.assert_awaited_once_with(file_id)
    service.storage.delete.assert_awaited_once()
    repo.delete_chunks_for_file.assert_awaited_once_with(file_id)
    repo.delete_file_record.assert_awaited_once_with(file_id)


async def test_remove_file_deletes_legacy_local_file_without_storage_key(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, _ = knowledge_service
    file_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    file_obj = SimpleNamespace(
        id=file_id,
        kb_id=kb_id,
        filename="legacy.md",
        file_path="/data/knowledge_files/legacy.md",
        file_size=10,
        content_sha256="sha256",
        storage_backend="local",
        storage_bucket=None,
        storage_key=None,
    )
    repo.get_file = AsyncMock(return_value=file_obj)
    repo.get_kb_for_user.return_value = SimpleNamespace(
        id=kb_id, user_id=user_id, workspace_id=None
    )
    repo.delete_chunks_for_file = AsyncMock()
    repo.delete_file_record = AsyncMock()
    service.storage.delete = AsyncMock()

    await service.remove_file(file_id=file_id, user_id=user_id)

    stored_object = service.storage.delete.await_args.args[0]
    assert stored_object.backend == "local"
    assert stored_object.key == ""
    assert stored_object.uri == "/data/knowledge_files/legacy.md"
    repo.delete_chunks_for_file.assert_awaited_once_with(file_id)
    repo.delete_file_record.assert_awaited_once_with(file_id)


async def test_remove_file_deletes_legacy_s3_file_from_uri_without_storage_key(
    knowledge_service: tuple[KnowledgeService, SimpleNamespace, Path],
) -> None:
    service, repo, _ = knowledge_service
    file_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    file_obj = SimpleNamespace(
        id=file_id,
        kb_id=kb_id,
        filename="legacy.md",
        file_path="s3://bucket-a/prefix/legacy.md",
        file_size=10,
        content_sha256="sha256",
        storage_backend="s3",
        storage_bucket=None,
        storage_key=None,
    )
    repo.get_file = AsyncMock(return_value=file_obj)
    repo.get_kb_for_user.return_value = SimpleNamespace(
        id=kb_id, user_id=user_id, workspace_id=None
    )
    repo.delete_chunks_for_file = AsyncMock()
    repo.delete_file_record = AsyncMock()
    service.storage.delete = AsyncMock()

    await service.remove_file(file_id=file_id, user_id=user_id)

    stored_object = service.storage.delete.await_args.args[0]
    assert stored_object.backend == "s3"
    assert stored_object.bucket == "bucket-a"
    assert stored_object.key == "prefix/legacy.md"
    assert stored_object.uri == "s3://bucket-a/prefix/legacy.md"
