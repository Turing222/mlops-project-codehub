import logging
import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException
from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.core.config import settings
from backend.core.exceptions import (
    DatabaseOperationError,
    ServiceError,
    ValidationError,
)
from backend.core.security import get_password_hash, verify_password
from backend.domain.interfaces import AbstractUnitOfWork
from backend.models.orm.user import User
from backend.models.schemas.user_schema import (
    UserBase,
    UserLogin,
    UserUpdate,
    UserCreate,
)
from backend.services.base import BaseService

# 模块级 logger，或者放在类里也可以
logger = logging.getLogger(__name__)


class UserService(BaseService[AbstractUnitOfWork]):
    def __init__(self, uow: AbstractUnitOfWork):
        super().__init__(uow)

    async def import_users(self, user_maps: list[dict]) -> int:
        """
        批量导入用户逻辑
        返回: 成功导入的数量
        """
        # 1. 基础校验

        if not user_maps:
            logger.info("No valid users data found in file")
            raise ValidationError("有效客户为0")

        incoming_usernames = [u["username"] for u in user_maps]

        try:
            # 2. 调用 CRUD 进行预验证 (直接用 self.uow.users)
            existing_names = await self.uow.users.get_existing_usernames(
                incoming_usernames
            )

            # 3. 业务规则校验
            if existing_names:
                raise ValidationError(f"以下用户名已被占用，无法注册: {existing_names}")

            # 4. 分批处理
            size = settings.BATCH_SIZE
            batches = [user_maps[i : i + size] for i in range(0, len(user_maps), size)]
            total_records = sum(len(b) for b in batches)
            total_batches = len(batches)

            for i, batch in enumerate(batches, 1):
                if not batch:
                    continue

                # 调用 uow
                await self.uow.users.bulk_upsert(batch)
                logger.debug(
                    f"批次 [{i}/{total_batches}] 处理完成，本批 {len(batch)} 条"
                )

            logger.info(f"批量处理成功, 成功提交 {total_records} 用户")
            return total_records

        except UnicodeDecodeError as e:
            raise ValidationError("Only UTF-8 CSV files are supported") from e
        except IntegrityError as e:
            raise DatabaseOperationError("数据违反了唯一性约束或其他限制") from e
        except SQLAlchemyError as e:
            raise DatabaseOperationError("数据库操作执行失败") from e
        except Exception as e:
            # Service 层捕获未知异常，转为统一的 ServiceError
            logger.exception("导入过程发生未知错误")  # 自动记录堆栈
            raise ServiceError("Internal server error during import") from e

    # --- 新增功能的扩展位置 ---

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

    # --- 简单透传逻辑 (Proxy) ---
    async def get_by_id(self, id: Any) -> User | None:
        """简单的透传，但保留了以后加逻辑的权利"""

        user = await self.uow.users.get(id)
        return user

    async def get_by_email(self, email: EmailStr) -> User | None:
        """简单的透传，但保留了以后加逻辑的权利"""

        user = await self.uow.users.get_by_email(email)
        return user

    async def get_by_username(self, username: str) -> User | None:
        """简单的透传，但保留了以后加逻辑的权利"""

        user = await self.uow.users.get_by_username(username)
        return user

    async def user_register(self, user_in: UserCreate) -> User | None:
        """
        新增：用户注册功能
        """
        logger.debug(f"当前变量值: {user_in}")

        # 1. 检查用户名是否存在
        if await self.uow.users.get_by_email(email=user_in.email):
            raise ValidationError("该邮箱已被注册")

        # 2. 密码加密 (这里是业务逻辑，不该放在 uow 里)

        obj_in_data = user_in.model_dump()  # Pydantic v2 用 model_dump
        obj_in_data.pop("password")  # 弹出明文密码
        obj_in_data.pop("confirm_password")  # 弹出明文密码
        logger.debug(f"当前密码: {user_in.password}")
        obj_in_data["hashed_password"] = await get_password_hash(
            user_in.password
        )  # 添加哈希密码

        # 3. 创建用户
        user = await self.uow.users.create(obj_in=obj_in_data)

        # 4. 可能还有后续动作，比如发送欢迎邮件...
        # await email_service.send_welcome_email(users.email)

        return user

    async def user_update(self, user_id: uuid.UUID, user_in: UserUpdate) -> User | None:
        """
        用户更新功能
        """
        db_obj = await self.uow.users.get(id=user_id)
        if not db_obj:
            raise HTTPException(status_code=404, detail="User not found")

        user = await self.uow.users.update(db_obj=db_obj, obj_in=user_in)
        return user

    async def authenticate(self, user_in: UserLogin) -> User | None:
        """验证用户名和密码"""

        user = await self.uow.users.get_by_username(user_in.username)
        if not user:
            return None
        if not verify_password(user_in.password, user.hashed_password):
            return None
        return user

    async def get_multi(self, skip: int = 0, limit: int = 100) -> Sequence[User] | None:
        users = await self.uow.users.get_multi(skip=skip, limit=limit)
        return users

    async def delete(self, id: int):
        # 比如删除前要做个检查？在这里加检查逻辑很方便
        # if id == 1: raise Error("不能删管理员")

        user = await self.uow.users.remove(id=id)
        return user
