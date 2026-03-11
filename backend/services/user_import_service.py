import asyncio

from fastapi import UploadFile

from backend.core.exceptions import ValidationError
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.schemas.user_schema import UserImportResponse
from backend.services.base import BaseService
from backend.services.user_service import UserService
from backend.utils.file_parser import parse_file


class UserImportService(BaseService[AbstractUnitOfWork]):
    """用户批量导入编排服务。"""

    async def import_from_upload(self, upload_file: UploadFile) -> UserImportResponse:
        if not upload_file.filename:
            raise ValidationError("文件名不能为空")

        content = await upload_file.read()
        if not content:
            raise ValidationError("上传文件为空")

        raw_data = await asyncio.to_thread(parse_file, upload_file.filename, content)
        total_rows = len(raw_data)
        cleaned_data = await UserService(self.uow).transform_and_validate(raw_data)

        async with self.uow:
            imported_rows = await UserService(self.uow).import_users(cleaned_data)

        return UserImportResponse(
            filename=upload_file.filename,
            total_rows=total_rows,
            imported_rows=imported_rows,
            message=f"成功导入 {imported_rows} 条用户数据",
        )
