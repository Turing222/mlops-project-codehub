# app/services/user_import_service.py
from typing import Any

from app.models.orm.user import UserBase  # 复用我们之前讨论的带 Annotated 的 Schema


class UserImportService:
    # 将映射关系定义为类常量，方便维护
    HEADER_MAP = {
        "用户名": "username",
        "邮箱": "email",
        "username": "username",
        "email": "email",
    }

    @classmethod
    async def transform_and_validate(
        cls, raw_data: list[dict[str, Any]]
    ) -> list[UserBase]:
        """
        核心中间层：执行字段映射、清洗和 Pydantic 校验
        """
        cleaned_schemas = []
        errors = []

        for index, row in enumerate(raw_data):
            # 1. 字段名映射 (Transform)
            mapped_row = {
                cls.HEADER_MAP[k]: v for k, v in row.items() if k in cls.HEADER_MAP
            }

            # 2. 利用 Pydantic 进行深度清洗与类型校验 (Validate)
            # 这样你就不需要手动写 if new_row.get("username") 了

            # model_validate 会触发我们之前写的 Annotated[BeforeValidator]
            # user_dto = UserBase.model_validate(mapped_row)if not mapped_row
            if mapped_row.get("username") and mapped_row.get("email"):
                cleaned_schemas.append(mapped_row)
            # except Exception as e:
            # B2B 场景建议记录哪一行出错了
            else:
                errors.append(f"Row {index}: {str(mapped_row)}")

        if not cleaned_schemas:
            raise ValueError(f"No valid data found. Errors: {errors}")
        if errors:
            raise ValueError(f"No valid data found. Errors: {errors}")
        return cleaned_schemas
