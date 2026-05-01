"""Object storage service.

职责：封装本地文件系统和 S3 的上传、删除、临时下载能力。
边界：本模块只处理对象存储，不创建知识库 File 记录。
失败处理：上传失败会清理临时文件或已写入对象，避免残留半成品。
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import uuid
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from fastapi import UploadFile

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class UploadSizeLimitExceeded(Exception):
    """上传流超过配置大小上限。"""


@dataclass(frozen=True, slots=True)
class StoredObject:
    """已保存对象的持久化定位信息。"""

    backend: str
    bucket: str | None
    key: str
    uri: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class UploadStreamStats:
    """上传流的大小和内容哈希。"""

    size: int
    sha256: str


class ObjectStorage(Protocol):
    """知识文件对象存储协议。"""

    backend: str

    async def save_upload_stream(
        self,
        *,
        kb_id: uuid.UUID,
        filename: str,
        upload_file: UploadFile,
        max_size_bytes: int,
    ) -> StoredObject: ...

    async def delete(self, stored_object: StoredObject) -> None: ...

    def download_to_temp(
        self,
        file_obj: object,
    ) -> AbstractAsyncContextManager[Path]: ...


class LocalObjectStorage:
    """本地文件系统对象存储实现。"""

    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = root

    async def save_upload_stream(
        self,
        *,
        kb_id: uuid.UUID,
        filename: str,
        upload_file: UploadFile,
        max_size_bytes: int,
    ) -> StoredObject:
        key = self._build_key(kb_id=kb_id, filename=filename)
        target_path = self.root / key
        temp_path = self.root / str(kb_id) / ".tmp" / f"{uuid.uuid4().hex}.part"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            stats = await _stream_upload_to_path(
                upload_file=upload_file,
                path=temp_path,
                max_size_bytes=max_size_bytes,
            )
            await asyncio.to_thread(temp_path.replace, target_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            target_path.unlink(missing_ok=True)
            raise

        return StoredObject(
            backend=self.backend,
            bucket=None,
            key=key,
            uri=str(target_path),
            size=stats.size,
            sha256=stats.sha256,
        )

    async def delete(self, stored_object: StoredObject) -> None:
        path = self._path_from_object(stored_object)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    @asynccontextmanager
    async def download_to_temp(self, file_obj: object) -> AsyncIterator[Path]:
        path = self._path_from_file(file_obj)
        if not path.exists():
            raise FileNotFoundError(str(path))
        yield path

    def _path_from_object(self, stored_object: StoredObject) -> Path:
        if stored_object.key:
            return self.root / stored_object.key
        return Path(stored_object.uri)

    def _path_from_file(self, file_obj: object) -> Path:
        storage_key = getattr(file_obj, "storage_key", None)
        if storage_key:
            return self.root / storage_key
        file_path = cast(Any, file_obj).file_path
        return Path(file_path)

    @staticmethod
    def _build_key(*, kb_id: uuid.UUID, filename: str) -> str:
        return f"{kb_id}/{uuid.uuid4().hex}_{filename}"


class S3ObjectStorage:
    """S3-compatible 对象存储实现。"""

    backend = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or self._create_client(
            region=region,
            endpoint_url=endpoint_url,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )

    async def save_upload_stream(
        self,
        *,
        kb_id: uuid.UUID,
        filename: str,
        upload_file: UploadFile,
        max_size_bytes: int,
    ) -> StoredObject:
        key = self._build_key(kb_id=kb_id, filename=filename)
        temp_path, stats = await _copy_upload_to_temp(
            upload_file=upload_file,
            max_size_bytes=max_size_bytes,
            suffix=Path(filename).suffix,
        )
        try:
            with temp_path.open("rb") as file_obj:
                await asyncio.to_thread(
                    self.client.upload_fileobj,
                    file_obj,
                    self.bucket,
                    key,
                    ExtraArgs={"Metadata": {"sha256": stats.sha256}},
                )
        except Exception:
            await asyncio.to_thread(
                self.client.delete_object,
                Bucket=self.bucket,
                Key=key,
            )
            raise
        finally:
            temp_path.unlink(missing_ok=True)

        return StoredObject(
            backend=self.backend,
            bucket=self.bucket,
            key=key,
            uri=f"s3://{self.bucket}/{key}",
            size=stats.size,
            sha256=stats.sha256,
        )

    async def delete(self, stored_object: StoredObject) -> None:
        await asyncio.to_thread(
            self.client.delete_object,
            Bucket=stored_object.bucket or self.bucket,
            Key=stored_object.key,
        )

    @asynccontextmanager
    async def download_to_temp(self, file_obj: object) -> AsyncIterator[Path]:
        key = getattr(file_obj, "storage_key", None) or _key_from_s3_uri(
            getattr(file_obj, "file_path", "")
        )
        if not key:
            raise FileNotFoundError("S3 object key is missing")

        suffix = Path(getattr(file_obj, "filename", "")).suffix
        temp_path = _new_temp_path(suffix=suffix)
        try:
            with temp_path.open("wb") as target:
                await asyncio.to_thread(
                    self.client.download_fileobj,
                    getattr(file_obj, "storage_bucket", None) or self.bucket,
                    key,
                    target,
                )
            yield temp_path
        finally:
            temp_path.unlink(missing_ok=True)

    def _build_key(self, *, kb_id: uuid.UUID, filename: str) -> str:
        relative = f"{kb_id}/{uuid.uuid4().hex}_{filename}"
        if not self.prefix:
            return relative
        return f"{self.prefix}/{relative}"

    @staticmethod
    def _create_client(
        *,
        region: str | None,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
    ):
        import boto3

        kwargs: dict[str, str] = {}
        if region:
            kwargs["region_name"] = region
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key_id:
            kwargs["aws_access_key_id"] = access_key_id
        if secret_access_key:
            kwargs["aws_secret_access_key"] = secret_access_key
        return boto3.client("s3", **kwargs)


def create_object_storage(settings) -> ObjectStorage:
    """按 Settings 构建对象存储实现。"""
    if settings.STORAGE_BACKEND == "local":
        return LocalObjectStorage(settings.local_storage_root)
    if not settings.S3_BUCKET:
        raise ValueError("S3_BUCKET must be configured when STORAGE_BACKEND=s3")
    return S3ObjectStorage(
        bucket=settings.S3_BUCKET,
        prefix=settings.S3_PREFIX,
        region=settings.S3_REGION,
        endpoint_url=settings.S3_ENDPOINT_URL,
        access_key_id=settings.S3_ACCESS_KEY_ID,
        secret_access_key=settings.S3_SECRET_ACCESS_KEY,
    )


async def _stream_upload_to_path(
    *,
    upload_file: UploadFile,
    path: Path,
    max_size_bytes: int,
) -> UploadStreamStats:
    total_size = 0
    hasher = hashlib.sha256()
    chunk_size = 1024 * 1024
    with path.open("wb") as target:
        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > max_size_bytes:
                raise UploadSizeLimitExceeded("upload exceeds max_size_bytes")
            hasher.update(chunk)
            target.write(chunk)
    return UploadStreamStats(size=total_size, sha256=hasher.hexdigest())


async def _copy_upload_to_temp(
    *,
    upload_file: UploadFile,
    max_size_bytes: int,
    suffix: str,
) -> tuple[Path, UploadStreamStats]:
    temp_path = _new_temp_path(suffix=suffix)
    try:
        stats = await _stream_upload_to_path(
            upload_file=upload_file,
            path=temp_path,
            max_size_bytes=max_size_bytes,
        )
        return temp_path, stats
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _new_temp_path(*, suffix: str) -> Path:
    temp_file = tempfile.NamedTemporaryFile(
        prefix="knowledge_",
        suffix=suffix,
        delete=False,
    )
    temp_file.close()
    return Path(temp_file.name)


def _key_from_s3_uri(uri: str) -> str:
    if not uri.startswith("s3://"):
        return ""
    path = uri.removeprefix("s3://")
    _, _, key = path.partition("/")
    return key
