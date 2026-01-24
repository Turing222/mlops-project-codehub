from typing import Any, Generic, TypeVar

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# 定义泛型变量
ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType")


class CRUDBase(Generic[ModelType, CreateSchemaType]):
    def __init__(self, model: type[ModelType]):
        """
        传入具体的 SQLModel 类，例如 User
        """
        self.model = model

    async def get(self, session: AsyncSession, id: Any) -> ModelType | None:
        return await session.get(self.model, id)

    async def get_multi(
        self, session: AsyncSession, *, skip: int = 0, limit: int = 100
    ):
        statement = select(self.model).offset(skip).limit(limit)
        result = await session.exec(statement)
        return result.all()

    async def create(
        self, session: AsyncSession, *, obj_in: CreateSchemaType
    ) -> ModelType:
        # 将 Schema 转换为 DB 模型
        db_obj = self.model.model_validate(obj_in)
        session.add(db_obj)
        await session.commit()
        await session.refresh(db_obj)
        return db_obj
