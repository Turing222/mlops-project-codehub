"""Object storage unit tests.

职责：验证 LocalObjectStorage 和 S3ObjectStorage 的上传、下载和清理行为；边界：使用 FakeS3Client 和 tmp_path，不连接真实 S3 或外部存储；副作用：无。
"""

from __future__ import annotations

import hashlib
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from backend.services.object_storage import (
    LocalObjectStorage,
    ObjectKeyBuilder,
    S3ObjectStorage,
    UploadSizeLimitExceeded,
)


def make_upload_file(filename: str, content: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename, size=len(content))


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict] = {}
        self.deleted: list[tuple[str, str]] = []

    def upload_fileobj(
        self,
        file_obj: object,
        bucket: str,
        key: str,
        ExtraArgs: dict | None = None,
    ) -> None:
        self.objects[(bucket, key)] = file_obj.read()
        self.metadata[(bucket, key)] = ExtraArgs or {}

    def download_fileobj(self, bucket: str, key: str, file_obj: object) -> None:
        file_obj.write(self.objects[(bucket, key)])

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)


class FailingUploadS3Client(FakeS3Client):
    def upload_fileobj(
        self,
        file_obj: object,
        bucket: str,
        key: str,
        ExtraArgs: dict | None = None,
    ) -> None:
        raise RuntimeError("upload failed")


class FailingUploadAndDeleteS3Client(FailingUploadS3Client):
    def delete_object(self, *, Bucket: str, Key: str) -> None:
        super().delete_object(Bucket=Bucket, Key=Key)
        raise RuntimeError("delete failed")


async def test_object_key_builder_builds_personal_knowledge_file_key() -> None:
    kb_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    owner_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    object_id = uuid.UUID("00000000-0000-0000-0000-000000000003")

    key = ObjectKeyBuilder().knowledge_file_key(
        kb_id=kb_id,
        owner_id=owner_id,
        workspace_id=None,
        filename="../demo.md",
        object_id=object_id,
    )

    assert key == (
        "v1/knowledge/users/00000000-0000-0000-0000-000000000002/"
        "kb/00000000-0000-0000-0000-000000000001/files/"
        "00000000-0000-0000-0000-000000000003_demo.md"
    )


async def test_object_key_builder_builds_workspace_knowledge_file_key() -> None:
    kb_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    owner_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    workspace_id = uuid.UUID("00000000-0000-0000-0000-000000000004")
    object_id = uuid.UUID("00000000-0000-0000-0000-000000000003")

    key = ObjectKeyBuilder().knowledge_file_key(
        kb_id=kb_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
        filename="demo.md",
        object_id=object_id,
    )

    assert key == (
        "v1/knowledge/workspaces/00000000-0000-0000-0000-000000000004/"
        "kb/00000000-0000-0000-0000-000000000001/files/"
        "00000000-0000-0000-0000-000000000003_demo.md"
    )


async def test_local_storage_saves_downloads_and_deletes_file(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    owner_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    upload = make_upload_file("demo.txt", b"hello")

    stored = await storage.save_upload_stream(
        kb_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        owner_id=owner_id,
        workspace_id=None,
        filename="demo.txt",
        upload_file=upload,
        max_size_bytes=1024,
    )

    assert stored.backend == "local"
    assert stored.key.startswith(
        "v1/knowledge/users/00000000-0000-0000-0000-000000000002/"
        "kb/00000000-0000-0000-0000-000000000001/files/"
    )
    assert stored.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert Path(stored.uri).read_bytes() == b"hello"
    async with storage.download_to_temp(
        type("FileObj", (), {"storage_key": stored.key, "file_path": stored.uri})()
    ) as path:
        assert path.read_bytes() == b"hello"

    await storage.delete(stored)
    assert not Path(stored.uri).exists()


async def test_local_storage_cleans_temp_file_on_size_limit(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    upload = make_upload_file("large.txt", b"too large")

    with pytest.raises(UploadSizeLimitExceeded):
        await storage.save_upload_stream(
            kb_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            owner_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            workspace_id=None,
            filename="large.txt",
            upload_file=upload,
            max_size_bytes=3,
        )

    assert list(tmp_path.rglob("*.part")) == []


async def test_s3_storage_saves_downloads_and_cleans_temp_file() -> None:
    client = FakeS3Client()
    storage = S3ObjectStorage(bucket="bucket-a", prefix="prefix", client=client)
    workspace_id = uuid.UUID("00000000-0000-0000-0000-000000000004")
    upload = make_upload_file("demo.txt", b"hello s3")

    stored = await storage.save_upload_stream(
        kb_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        owner_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        workspace_id=workspace_id,
        filename="demo.txt",
        upload_file=upload,
        max_size_bytes=1024,
    )

    assert stored.backend == "s3"
    assert stored.bucket == "bucket-a"
    assert stored.key.startswith(
        "prefix/v1/knowledge/workspaces/"
        "00000000-0000-0000-0000-000000000004/"
        "kb/00000000-0000-0000-0000-000000000001/files/"
    )
    assert stored.sha256 == hashlib.sha256(b"hello s3").hexdigest()
    assert client.objects[("bucket-a", stored.key)] == b"hello s3"
    assert client.metadata[("bucket-a", stored.key)] == {
        "Metadata": {"sha256": stored.sha256}
    }

    file_obj = type(
        "FileObj",
        (),
        {
            "storage_bucket": stored.bucket,
            "storage_key": stored.key,
            "file_path": stored.uri,
            "filename": "demo.txt",
        },
    )()
    async with storage.download_to_temp(file_obj) as path:
        temp_path = path
        assert path.read_bytes() == b"hello s3"
    assert not temp_path.exists()

    await storage.delete(stored)
    assert ("bucket-a", stored.key) in client.deleted


async def test_s3_storage_deletes_object_on_upload_failure() -> None:
    client = FailingUploadS3Client()
    storage = S3ObjectStorage(bucket="bucket-a", client=client)
    upload = make_upload_file("demo.txt", b"hello s3")

    with pytest.raises(RuntimeError, match="upload failed"):
        await storage.save_upload_stream(
            kb_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            owner_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            workspace_id=None,
            filename="demo.txt",
            upload_file=upload,
            max_size_bytes=1024,
        )

    assert len(client.deleted) == 1


async def test_s3_upload_failure_keeps_original_error_when_cleanup_fails() -> None:
    client = FailingUploadAndDeleteS3Client()
    storage = S3ObjectStorage(bucket="bucket-a", client=client)
    upload = make_upload_file("demo.txt", b"hello s3")

    with pytest.raises(RuntimeError, match="upload failed"):
        await storage.save_upload_stream(
            kb_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            owner_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            workspace_id=None,
            filename="demo.txt",
            upload_file=upload,
            max_size_bytes=1024,
        )

    assert len(client.deleted) == 1
