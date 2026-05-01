"""Knowledge base file service.

职责：校验知识库访问、保存上传对象、去重并创建文件记录。
边界：本模块不解析文件内容、不生成向量；入库处理由 KnowledgeRAGWorkflow 负责。
失败处理：数据库记录创建失败时会删除已保存对象，避免产生孤儿文件。
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import (
    AppException,
    app_not_found,
    app_service_error,
    app_validation_error,
)
from backend.models.orm.knowledge import File, FileStatus, KnowledgeBase
from backend.services.object_storage import (
    LocalObjectStorage,
    ObjectStorage,
    StoredObject,
    UploadSizeLimitExceeded,
)
from backend.services.permission_service import Permission, PermissionService

DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_KNOWLEDGE_BASE_DESCRIPTION = "系统自动创建的默认知识库"


@dataclass(frozen=True, slots=True)
class SavedKnowledgeFile:
    """上传保存结果和是否需要后续入库。"""

    file: File
    should_ingest: bool
    deduplicated: bool


class KnowledgeService:
    """知识库文件保存和访问校验服务。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        storage: ObjectStorage | None = None,
        storage_root: Path | None = None,
        max_upload_size_mb: int = 20,
    ) -> None:
        self.uow = uow
        if storage is None:
            if storage_root is None:
                raise ValueError("storage or storage_root is required")
            storage = LocalObjectStorage(storage_root)
        self.storage = storage
        self.max_upload_size_mb = max(1, max_upload_size_mb)
        self.max_upload_size_bytes = self.max_upload_size_mb * 1024 * 1024

    async def save_upload_file(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        upload_file: UploadFile,
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
        upload_file: UploadFile,
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
                filename=safe_filename,
                upload_file=upload_file,
                max_size_bytes=self.max_upload_size_bytes,
            )
            if stored_object.size <= 0:
                raise app_validation_error("上传文件为空", code="UPLOAD_FILE_EMPTY")

            duplicate = await self.uow.knowledge_repo.get_ready_file_by_hash(
                kb_id=kb_id,
                content_sha256=stored_object.sha256,
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

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        base = Path(filename).name.strip()
        if not base:
            return "unnamed.txt"
        base = base.replace("\x00", "")
        return base

    def _validate_upload_file(self, upload_file: UploadFile) -> str:
        if not upload_file.filename:
            raise app_validation_error(
                "上传文件名不能为空", code="UPLOAD_FILENAME_EMPTY"
            )

        safe_filename = self._sanitize_filename(upload_file.filename)
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

        get_kb = getattr(self.uow.knowledge_repo, "get_kb", None)
        if get_kb is None:
            if kb:
                return kb
            raise app_not_found(
                "知识库不存在或无访问权限", code="KNOWLEDGE_BASE_NOT_FOUND"
            )

        full_kb = kb or await get_kb(kb_id)
        if not full_kb:
            raise app_not_found(
                "知识库不存在或无访问权限", code="KNOWLEDGE_BASE_NOT_FOUND"
            )

        # workspace KB 必须按当前成员角色判断，避免历史 owner 身份绕过权限。
        if full_kb.workspace_id is not None:
            if await PermissionService(self.uow).has_permission_for_user_id(
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
