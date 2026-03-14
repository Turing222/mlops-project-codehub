import asyncio
import logging
import secrets
from typing import Any

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.core.config import settings
from backend.core.exceptions import (
    AppError,
    DatabaseOperationError,
    ServiceError,
    ValidationError,
)
from backend.core.security import get_password_hash
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.schemas.user_schema import UserImportResponse
from backend.services.base import BaseService
from backend.utils.file_parser import parse_file

logger = logging.getLogger(__name__)


class UserImportService(BaseService[AbstractUnitOfWork]):
    """用户批量导入编排服务。"""

    HEADER_MAP = {
        "用户名": "username",
        "邮箱": "email",
        "username": "username",
        "email": "email",
    }

    async def import_from_upload(self, upload_file: UploadFile) -> UserImportResponse:
        if not upload_file.filename:
            raise ValidationError("文件名不能为空")

        content = await upload_file.read()
        if not content:
            raise ValidationError("上传文件为空")

        raw_data = await asyncio.to_thread(parse_file, upload_file.filename, content)
        total_rows = len(raw_data)
        cleaned_data = await self.transform_and_validate(raw_data)

        async with self.uow:
            imported_rows = await self.import_users(cleaned_data)

        return UserImportResponse(
            filename=upload_file.filename,
            total_rows=total_rows,
            imported_rows=imported_rows,
            message=f"成功导入 {imported_rows} 条用户数据",
        )

    async def import_users(self, user_maps: list[dict[str, Any]]) -> int:
        """批量导入用户，返回成功导入数量。"""
        if not user_maps:
            logger.info("No valid users data found in file")
            raise ValidationError("有效客户为0")

        incoming_usernames = [str(u["username"]) for u in user_maps]

        try:
            existing_names = await self.uow.user_repo.get_existing_usernames(
                incoming_usernames
            )
            if existing_names:
                raise ValidationError(f"以下用户名已被占用，无法注册: {existing_names}")

            size = settings.BATCH_SIZE
            batches = [user_maps[i : i + size] for i in range(0, len(user_maps), size)]
            total_records = sum(len(batch) for batch in batches)
            total_batches = len(batches)

            for idx, batch in enumerate(batches, 1):
                if not batch:
                    continue
                import_rows = await self._build_import_rows(batch)
                await self.uow.user_repo.bulk_upsert(import_rows)
                await self._after_import_batch_hook(import_rows)
                logger.debug("批次 [%d/%d] 处理完成，本批 %d 条", idx, total_batches, len(batch))

            logger.info("批量处理成功, 成功提交 %d 用户", total_records)
            return total_records
        except AppError:
            raise
        except IntegrityError as exc:
            raise DatabaseOperationError("数据违反了唯一性约束或其他限制") from exc
        except SQLAlchemyError as exc:
            raise DatabaseOperationError("数据库操作执行失败") from exc
        except Exception as exc:
            logger.exception("导入过程发生未知错误")
            raise ServiceError("Internal server error during import") from exc

    @classmethod
    async def transform_and_validate(
        cls, raw_data: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """执行字段映射、清洗与基础校验。"""
        cleaned_schemas: list[dict[str, Any]] = []
        errors: list[str] = []

        for index, row in enumerate(raw_data):
            mapped_row = {cls.HEADER_MAP[k]: v for k, v in row.items() if k in cls.HEADER_MAP}
            if mapped_row.get("username") and mapped_row.get("email"):
                cleaned_schemas.append(mapped_row)
            else:
                errors.append(f"Row {index}: {mapped_row}")

        if not cleaned_schemas:
            raise ValidationError(f"No valid data found. Errors: {errors}")
        if errors:
            raise ValidationError(f"No valid data found. Errors: {errors}")
        return cleaned_schemas

    async def _build_import_rows(self, user_maps: list[dict[str, Any]]) -> list[dict[str, str]]:
        """构造可直接入库的数据行（补齐 hashed_password）。"""
        rows: list[dict[str, str]] = []
        for user_map in user_maps:
            username = str(user_map["username"]).strip().lower()
            email = str(user_map["email"]).strip().lower()
            temp_password = secrets.token_urlsafe(12)
            hashed_password = await get_password_hash(temp_password)
            rows.append(
                {
                    "username": username,
                    "email": email,
                    "hashed_password": hashed_password,
                }
            )
        return rows

    async def _after_import_batch_hook(self, import_rows: list[dict[str, str]]) -> None:
        """导入后扩展钩子（预留给激活流程/通知流程）。"""
        _ = import_rows
