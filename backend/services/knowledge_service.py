import asyncio
import uuid
from pathlib import Path

from fastapi import UploadFile

from backend.core.exceptions import ResourceNotFound, ValidationError
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.knowledge import File, FileStatus


class KnowledgeService:
    def __init__(
        self,
        uow: AbstractUnitOfWork,
        storage_root: Path,
    ):
        self.uow = uow
        self.storage_root = storage_root

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
        content = await upload_file.read()
        if not content:
            raise ValidationError("上传文件为空")

        async with self.uow:
            kb = await self.uow.knowledge.get_kb_for_user(kb_id=kb_id, user_id=user_id)
            if not kb:
                raise ResourceNotFound("知识库不存在或无访问权限")

        target_path = self._build_storage_path(kb_id=kb_id, filename=safe_filename)
        await asyncio.to_thread(self._write_file, target_path, content)

        try:
            async with self.uow:
                file_obj = await self.uow.knowledge.create_file(
                    kb_id=kb_id,
                    filename=safe_filename,
                    file_path=str(target_path),
                    file_size=len(content),
                    status=FileStatus.UPLOADED,
                )
        except Exception:
            target_path.unlink(missing_ok=True)
            raise

        return file_obj

    async def get_file(self, file_id: uuid.UUID) -> File | None:
        async with self.uow:
            return await self.uow.knowledge.get_file(file_id)

    async def ensure_kb_access(self, *, kb_id: uuid.UUID, user_id: uuid.UUID) -> None:
        async with self.uow:
            kb = await self.uow.knowledge.get_kb_for_user(kb_id=kb_id, user_id=user_id)
            if not kb:
                raise ResourceNotFound("知识库不存在或无访问权限")

    async def set_file_status(
        self,
        *,
        file_id: uuid.UUID,
        status: FileStatus,
    ) -> File | None:
        async with self.uow:
            return await self.uow.knowledge.update_file_status(file_id=file_id, status=status)

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
