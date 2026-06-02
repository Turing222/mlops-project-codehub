"""Knowledge base file service.

职责：校验知识库访问、保存上传对象、去重并创建文件记录。
边界：本模块不解析文件内容、不生成向量；入库处理由 KnowledgeRAGWorkflow 负责。
失败处理：数据库记录创建失败时会删除已保存对象，避免产生孤儿文件。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.contracts.uploads import UploadFileLike
from backend.core.constants import SUPPORTED_KNOWLEDGE_SUFFIXES
from backend.core.exceptions import (
    AppException,
    app_not_found,
    app_service_error,
    app_validation_error,
)
from backend.models.orm.knowledge import File, FileStatus, KnowledgeBase
from backend.services.base import BaseService
from backend.services.object_storage import (
    LocalObjectStorage,
    ObjectStorage,
    StoredObject,
    UploadSizeLimitExceeded,
    safe_storage_filename,
)
from backend.services.permission_service import Permission, PermissionService

logger = logging.getLogger(__name__)

DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_KNOWLEDGE_BASE_DESCRIPTION = "系统自动创建的默认知识库"


@dataclass(frozen=True, slots=True)
class SavedKnowledgeFile:
    """上传保存结果和是否需要后续入库。"""

    file: File
    should_ingest: bool
    deduplicated: bool


class KnowledgeService(BaseService[AbstractUnitOfWork]):
    """知识库文件保存和访问校验服务。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        permission_service: PermissionService,
        storage: ObjectStorage | None = None,
        storage_root: Path | None = None,
        max_upload_size_mb: int = 20,
    ) -> None:
        super().__init__(uow)
        if storage is None:
            if storage_root is None:
                raise ValueError("storage or storage_root is required")
            storage = LocalObjectStorage(storage_root)
        self.storage = storage
        self.max_upload_size_mb = max(1, max_upload_size_mb)
        self.max_upload_size_bytes = self.max_upload_size_mb * 1024 * 1024
        self._permission_service = permission_service

    async def save_upload_file(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        upload_file: UploadFileLike,
    ) -> File:
        result = await self.save_upload_file_for_ingestion(
            kb_id=kb_id,
            user_id=user_id,
            upload_file=upload_file,
        )
        return result.file

    async def save_upload_file_for_ingestion(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        upload_file: UploadFileLike,
    ) -> SavedKnowledgeFile:
        safe_filename = self._validate_upload_file(upload_file)
        kb = await self._ensure_kb_access(
            kb_id=kb_id,
            user_id=user_id,
            permission=Permission.FILE_WRITE,
        )

        stored_object: StoredObject | None = None
        try:
            stored_object = await self.storage.save_upload_stream(
                kb_id=kb_id,
                owner_id=user_id,
                workspace_id=getattr(kb, "workspace_id", None),
                filename=safe_filename,
                upload_file=upload_file,
                max_size_bytes=self.max_upload_size_bytes,
            )
            if stored_object.size <= 0:
                raise app_validation_error("上传文件为空", code="UPLOAD_FILE_EMPTY")

            duplicate = await self.uow.knowledge_repo.get_file_by_hash_and_status(
                kb_id=kb_id,
                content_sha256=stored_object.sha256,
                status=FileStatus.READY,
            )
            if duplicate is not None:
                await self.storage.delete(stored_object)
                return SavedKnowledgeFile(
                    file=duplicate,
                    should_ingest=False,
                    deduplicated=True,
                )

            file_obj = await self._create_file_record(
                kb_id=kb_id,
                filename=safe_filename,
                stored_object=stored_object,
                owner_id=user_id,
                workspace_id=getattr(kb, "workspace_id", None),
            )
            return SavedKnowledgeFile(
                file=file_obj,
                should_ingest=True,
                deduplicated=False,
            )
        except AppException:
            if stored_object is not None:
                await self.storage.delete(stored_object)
            raise
        except UploadSizeLimitExceeded as exc:
            if stored_object is not None:
                await self.storage.delete(stored_object)
            raise app_validation_error(
                f"上传文件超过大小限制（最大 {self.max_upload_size_mb}MB）",
                code="UPLOAD_FILE_TOO_LARGE",
            ) from exc
        except Exception as exc:
            if stored_object is not None:
                await self.storage.delete(stored_object)
            raise app_service_error(
                "上传文件保存失败，请稍后重试",
                code="UPLOAD_FILE_SAVE_FAILED",
            ) from exc

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

    async def try_transition_file_status(
        self,
        *,
        file_id: uuid.UUID,
        expected_previous_statuses: Collection[FileStatus],
        target_status: FileStatus,
    ) -> bool:
        return await self.uow.knowledge_repo.try_transition_file_status(
            file_id=file_id,
            expected_previous_statuses=expected_previous_statuses,
            target_status=target_status,
        )

    async def delete_chunks_for_file(self, *, file_id: uuid.UUID) -> None:
        await self.uow.knowledge_repo.delete_chunks_for_file(file_id=file_id)

    async def list_files_by_kb_id(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Sequence[File]:
        await self._ensure_kb_access(
            kb_id=kb_id,
            user_id=user_id,
            permission=Permission.FILE_READ,
        )
        return await self.uow.knowledge_repo.list_files_by_kb(kb_id)

    async def remove_file(
        self,
        *,
        file_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        file_obj = await self.get_file(file_id)
        if not file_obj:
            raise app_not_found("文件不存在", code="KNOWLEDGE_FILE_NOT_FOUND")

        await self._ensure_kb_access(
            kb_id=file_obj.kb_id,
            user_id=user_id,
            permission=Permission.FILE_WRITE,
        )

        stored_obj = self._stored_object_from_file(file_obj)
        if stored_obj is not None:
            try:
                await self.storage.delete(stored_obj)
            except Exception:
                logger.warning(
                    "Storage delete failed for backend=%s key=%s uri=%s",
                    stored_obj.backend,
                    stored_obj.key,
                    stored_obj.uri,
                    exc_info=True,
                )

        await self.uow.knowledge_repo.delete_chunks_for_file(file_id)
        await self.uow.knowledge_repo.delete_file_record(file_id)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        return safe_storage_filename(filename)

    @staticmethod
    def _stored_object_from_file(file_obj: File) -> StoredObject | None:
        file_path = file_obj.file_path or ""
        storage_key = file_obj.storage_key or ""
        storage_bucket = file_obj.storage_bucket
        storage_backend = file_obj.storage_backend or (
            "s3" if file_path.startswith("s3://") else "local"
        )

        if storage_backend == "s3" and not storage_key:
            parsed = urlparse(file_path)
            if parsed.scheme == "s3":
                storage_bucket = storage_bucket or parsed.netloc
                storage_key = parsed.path.lstrip("/")

        if storage_backend == "s3" and not storage_key:
            return None
        if storage_backend == "local" and not storage_key and not file_path:
            return None

        return StoredObject(
            backend=storage_backend,
            bucket=storage_bucket,
            key=storage_key,
            uri=file_path,
            size=file_obj.file_size,
            sha256=file_obj.content_sha256 or "",
        )

    def _validate_upload_file(self, upload_file: UploadFileLike) -> str:
        if not upload_file.filename:
            raise app_validation_error(
                "上传文件名不能为空", code="UPLOAD_FILENAME_EMPTY"
            )

        safe_filename = self._sanitize_filename(upload_file.filename)
        suffix = Path(safe_filename).suffix.lower()
        if suffix not in SUPPORTED_KNOWLEDGE_SUFFIXES:
            raise app_validation_error(
                "当前仅支持 Markdown 文件",
                code="KNOWLEDGE_FILE_UNSUPPORTED_TYPE",
                details={
                    "filename": safe_filename,
                    "supported_suffixes": sorted(SUPPORTED_KNOWLEDGE_SUFFIXES),
                },
            )
        if upload_file.size and upload_file.size > self.max_upload_size_bytes:
            raise app_validation_error(
                f"上传文件超过大小限制（最大 {self.max_upload_size_mb}MB）",
                code="UPLOAD_FILE_TOO_LARGE",
            )
        return safe_filename

    async def _ensure_kb_access(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        permission: Permission,
    ) -> KnowledgeBase:
        # personal KB 可以走 owner 快捷路径，workspace KB 仍需后续角色校验。
        kb = await self.uow.knowledge_repo.get_kb_for_user(
            kb_id=kb_id,
            user_id=user_id,
        )

        full_kb = kb or await self.uow.knowledge_repo.get_kb(kb_id)
        if not full_kb:
            raise app_not_found(
                "知识库不存在或无访问权限", code="KNOWLEDGE_BASE_NOT_FOUND"
            )

        # workspace KB 必须按当前成员角色判断，避免历史 owner 身份绕过权限。
        if full_kb.workspace_id is not None:
            if await self._permission_service.has_permission_for_user_id(
                user_id=user_id,
                workspace_id=full_kb.workspace_id,
                permission=permission,
            ):
                return full_kb
            raise app_not_found(
                "知识库不存在或无访问权限", code="KNOWLEDGE_BASE_NOT_FOUND"
            )

        # personal KB 没有 workspace 角色，只有 owner 可访问。
        if full_kb.user_id == user_id:
            return full_kb

        raise app_not_found("知识库不存在或无访问权限", code="KNOWLEDGE_BASE_NOT_FOUND")

    async def _create_file_record(
        self,
        *,
        kb_id: uuid.UUID,
        filename: str,
        stored_object: StoredObject,
        owner_id: uuid.UUID,
        workspace_id: uuid.UUID | None,
    ) -> File:
        try:
            return await self.uow.knowledge_repo.create_file(
                kb_id=kb_id,
                filename=filename,
                file_path=stored_object.uri,
                file_size=stored_object.size,
                status=FileStatus.UPLOADED,
                owner_id=owner_id,
                workspace_id=workspace_id,
                storage_backend=stored_object.backend,
                storage_bucket=stored_object.bucket,
                storage_key=stored_object.key,
                content_sha256=stored_object.sha256,
            )
        except AppException:
            await self.storage.delete(stored_object)
            raise
        except Exception as exc:
            await self.storage.delete(stored_object)
            raise app_service_error(
                "上传文件保存失败，请稍后重试",
                code="UPLOAD_FILE_SAVE_FAILED",
            ) from exc
