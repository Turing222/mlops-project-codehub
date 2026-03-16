import asyncio
import uuid
from pathlib import Path

from fastapi import UploadFile

from backend.core.exceptions import (
    AppError,
    ResourceNotFound,
    ServiceError,
    ValidationError,
)
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.knowledge import File, FileStatus


class KnowledgeService:
    def __init__(
        self,
        uow: AbstractUnitOfWork,
        storage_root: Path,
        max_upload_size_mb: int = 20,
    ):
        self.uow = uow
        self.storage_root = storage_root
        self.max_upload_size_mb = max(1, max_upload_size_mb)
        self.max_upload_size_bytes = self.max_upload_size_mb * 1024 * 1024

    async def save_upload_file(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        upload_file: UploadFile,
    ) -> File:
        if not upload_file.filename:
            raise ValidationError("上传文件名不能为空")

        safe_filename = self._sanitize_filename(upload_file.filename)
        if upload_file.size and upload_file.size > self.max_upload_size_bytes:
            raise ValidationError(
                f"上传文件超过大小限制（最大 {self.max_upload_size_mb}MB）"
            )
        content = await self._read_upload_content(upload_file)
        if not content:
            raise ValidationError("上传文件为空")

        kb = await self.uow.knowledge_repo.get_kb_for_user(kb_id=kb_id, user_id=user_id)
        if not kb:
            raise ResourceNotFound("知识库不存在或无访问权限")

        target_path = self._build_storage_path(kb_id=kb_id, filename=safe_filename)
        await asyncio.to_thread(self._write_file, target_path, content)

        try:
            file_obj = await self.uow.knowledge_repo.create_file(
                kb_id=kb_id,
                filename=safe_filename,
                file_path=str(target_path),
                file_size=len(content),
                status=FileStatus.UPLOADED,
            )
        except AppError:
            target_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            target_path.unlink(missing_ok=True)
            raise ServiceError("上传文件保存失败，请稍后重试") from exc

        return file_obj

    async def get_file(self, file_id: uuid.UUID) -> File | None:
        return await self.uow.knowledge_repo.get_file(file_id)

    async def ensure_kb_access(self, *, kb_id: uuid.UUID, user_id: uuid.UUID) -> None:
        kb = await self.uow.knowledge_repo.get_kb_for_user(kb_id=kb_id, user_id=user_id)
        if not kb:
            raise ResourceNotFound("知识库不存在或无访问权限")

    async def set_file_status(
        self,
        *,
        file_id: uuid.UUID,
        status: FileStatus,
    ) -> File | None:
        return await self.uow.knowledge_repo.update_file_status(file_id=file_id, status=status)

    def _build_storage_path(self, *, kb_id: uuid.UUID, filename: str) -> Path:
        kb_dir = self.storage_root / str(kb_id)
        kb_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        return kb_dir / unique_name

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        base = Path(filename).name.strip()
        if not base:
            return "unnamed.txt"
        base = base.replace("\x00", "")
        return base

    @staticmethod
    def _write_file(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            f.write(content)

    async def _read_upload_content(self, upload_file: UploadFile) -> bytes:
        chunks: list[bytes] = []
        total_size = 0
        chunk_size = 1024 * 1024

        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > self.max_upload_size_bytes:
                raise ValidationError(
                    f"上传文件超过大小限制（最大 {self.max_upload_size_mb}MB）"
                )
            chunks.append(chunk)

        return b"".join(chunks)
