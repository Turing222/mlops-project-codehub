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
from backend.models.orm.knowledge import File, FileStatus, KnowledgeBase
from backend.services.permission_service import Permission, PermissionService

DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_KNOWLEDGE_BASE_DESCRIPTION = "系统自动创建的默认知识库"


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
        safe_filename = self._validate_upload_file(upload_file)
        content = await self._read_upload_content(upload_file)
        if not content:
            raise ValidationError("上传文件为空")

        kb = await self._ensure_kb_access(
            kb_id=kb_id,
            user_id=user_id,
            permission=Permission.FILE_WRITE,
        )

        target_path = self._build_storage_path(kb_id=kb_id, filename=safe_filename)
        await asyncio.to_thread(self._write_file, target_path, content)

        return await self._create_file_record(
            kb_id=kb_id,
            filename=safe_filename,
            file_path=target_path,
            file_size=len(content),
            owner_id=user_id,
            workspace_id=getattr(kb, "workspace_id", None),
        )

    async def save_upload_file_streaming(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        upload_file: UploadFile,
    ) -> File:
        safe_filename = self._validate_upload_file(upload_file)
        kb = await self._ensure_kb_access(
            kb_id=kb_id,
            user_id=user_id,
            permission=Permission.FILE_WRITE,
        )

        target_path = self._build_storage_path(kb_id=kb_id, filename=safe_filename)
        temp_path = self._build_temp_storage_path(kb_id=kb_id, filename=safe_filename)
        moved_to_target = False

        try:
            file_size = await self._stream_upload_to_file(upload_file, temp_path)
            if file_size <= 0:
                raise ValidationError("上传文件为空")

            await asyncio.to_thread(self._move_file, temp_path, target_path)
            moved_to_target = True

            return await self._create_file_record(
                kb_id=kb_id,
                filename=safe_filename,
                file_path=target_path,
                file_size=file_size,
                owner_id=user_id,
                workspace_id=getattr(kb, "workspace_id", None),
            )
        except AppError:
            self._cleanup_file(target_path if moved_to_target else temp_path)
            raise
        except Exception as exc:
            self._cleanup_file(target_path if moved_to_target else temp_path)
            raise ServiceError("上传文件保存失败，请稍后重试") from exc

    async def get_file(self, file_id: uuid.UUID) -> File | None:
        return await self.uow.knowledge_repo.get_file(file_id)

    async def get_default_kb_for_user(
        self,
        *,
        user_id: uuid.UUID,
    ) -> KnowledgeBase | None:
        return await self.uow.knowledge_repo.get_kb_by_name_for_user(
            name=DEFAULT_KNOWLEDGE_BASE_NAME,
            user_id=user_id,
        )

    async def get_or_create_default_kb(
        self,
        *,
        user_id: uuid.UUID,
    ) -> KnowledgeBase:
        kb = await self.get_default_kb_for_user(user_id=user_id)
        if kb:
            return kb

        return await self.uow.knowledge_repo.create_kb(
            name=DEFAULT_KNOWLEDGE_BASE_NAME,
            description=DEFAULT_KNOWLEDGE_BASE_DESCRIPTION,
            user_id=user_id,
        )

    async def ensure_kb_access(self, *, kb_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self._ensure_kb_access(
            kb_id=kb_id,
            user_id=user_id,
            permission=Permission.FILE_READ,
        )

    async def set_file_status(
        self,
        *,
        file_id: uuid.UUID,
        status: FileStatus,
    ) -> File | None:
        return await self.uow.knowledge_repo.update_file_status(
            file_id=file_id, status=status
        )

    def _build_storage_path(self, *, kb_id: uuid.UUID, filename: str) -> Path:
        kb_dir = self.storage_root / str(kb_id)
        kb_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        return kb_dir / unique_name

    def _build_temp_storage_path(self, *, kb_id: uuid.UUID, filename: str) -> Path:
        tmp_dir = self.storage_root / str(kb_id) / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f"{uuid.uuid4().hex}_{filename}.part"
        return tmp_dir / unique_name

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

    @staticmethod
    def _move_file(src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)

    @staticmethod
    def _cleanup_file(path: Path) -> None:
        path.unlink(missing_ok=True)

    def _validate_upload_file(self, upload_file: UploadFile) -> str:
        if not upload_file.filename:
            raise ValidationError("上传文件名不能为空")

        safe_filename = self._sanitize_filename(upload_file.filename)
        if upload_file.size and upload_file.size > self.max_upload_size_bytes:
            raise ValidationError(
                f"上传文件超过大小限制（最大 {self.max_upload_size_mb}MB）"
            )
        return safe_filename

    async def _ensure_kb_access(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        permission: Permission,
    ) -> KnowledgeBase:
        # 先通过 owner+personal 快捷路径查询（仅返回该用户名下且无 workspace 绑定的 KB）
        kb = await self.uow.knowledge_repo.get_kb_for_user(
            kb_id=kb_id,
            user_id=user_id,
        )

        get_kb = getattr(self.uow.knowledge_repo, "get_kb", None)
        if get_kb is None:
            if kb:
                return kb
            raise ResourceNotFound("知识库不存在或无访问权限")

        # 取完整 KB 对象（含 workspace_id）
        full_kb = kb or await get_kb(kb_id)
        if not full_kb:
            raise ResourceNotFound("知识库不存在或无访问权限")

        # ① workspace KB：无论是否 owner，必须验证当前 workspace 成员权限
        #    防止用户被移出/降级后仍凭 KB owner 身份绕过权限
        if full_kb.workspace_id is not None:
            if await PermissionService(self.uow).has_permission_for_user_id(
                user_id=user_id,
                workspace_id=full_kb.workspace_id,
                permission=permission,
            ):
                return full_kb
            raise ResourceNotFound("知识库不存在或无访问权限")

        # ② personal KB（workspace_id is None）：仅 owner 可访问
        if full_kb.user_id == user_id:
            return full_kb

        raise ResourceNotFound("知识库不存在或无访问权限")

    async def _create_file_record(
        self,
        *,
        kb_id: uuid.UUID,
        filename: str,
        file_path: Path,
        file_size: int,
        owner_id: uuid.UUID,
        workspace_id: uuid.UUID | None,
    ) -> File:
        try:
            return await self.uow.knowledge_repo.create_file(
                kb_id=kb_id,
                filename=filename,
                file_path=str(file_path),
                file_size=file_size,
                status=FileStatus.UPLOADED,
                owner_id=owner_id,
                workspace_id=workspace_id,
            )
        except AppError:
            self._cleanup_file(file_path)
            raise
        except Exception as exc:
            self._cleanup_file(file_path)
            raise ServiceError("上传文件保存失败，请稍后重试") from exc

    async def _stream_upload_to_file(self, upload_file: UploadFile, path: Path) -> int:
        total_size = 0
        chunk_size = 1024 * 1024

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > self.max_upload_size_bytes:
                    raise ValidationError(
                        f"上传文件超过大小限制（最大 {self.max_upload_size_mb}MB）"
                    )
                await asyncio.to_thread(f.write, chunk)

        return total_size

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
