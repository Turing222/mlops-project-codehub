from __future__ import annotations

import hashlib
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from backend.services.object_storage import LocalObjectStorage, S3ObjectStorage


def make_upload_file(filename: str, content: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename, size=len(content))


class FakeS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict] = {}
        self.deleted: list[tuple[str, str]] = []

    def upload_fileobj(
        self,
        file_obj,
        bucket: str,
        key: str,
        ExtraArgs: dict | None = None,
    ) -> None:
        self.objects[(bucket, key)] = file_obj.read()
        self.metadata[(bucket, key)] = ExtraArgs or {}

    def download_fileobj(self, bucket: str, key: str, file_obj) -> None:
        file_obj.write(self.objects[(bucket, key)])

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)


@pytest.mark.asyncio
async def test_local_object_storage_saves_downloads_and_deletes(tmp_path: Path):
    storage = LocalObjectStorage(tmp_path)
    upload = make_upload_file("demo.txt", b"hello")

    stored = await storage.save_upload_stream(
        kb_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        filename="demo.txt",
        upload_file=upload,
        max_size_bytes=1024,
    )

    assert stored.backend == "local"
    assert stored.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert Path(stored.uri).read_bytes() == b"hello"
    async with storage.download_to_temp(
        type("FileObj", (), {"storage_key": stored.key, "file_path": stored.uri})()
    ) as path:
        assert path.read_bytes() == b"hello"

    await storage.delete(stored)
    assert not Path(stored.uri).exists()


@pytest.mark.asyncio
async def test_s3_object_storage_saves_downloads_and_cleans_temp_file():
    client = FakeS3Client()
    storage = S3ObjectStorage(bucket="bucket-a", prefix="prefix", client=client)
    upload = make_upload_file("demo.txt", b"hello s3")

    stored = await storage.save_upload_stream(
        kb_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        filename="demo.txt",
        upload_file=upload,
        max_size_bytes=1024,
    )

    assert stored.backend == "s3"
    assert stored.bucket == "bucket-a"
    assert stored.key.startswith("prefix/")
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
