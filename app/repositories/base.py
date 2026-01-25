from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)


class BaseRepo:
    def __init__(self, session):
        self.session = session

    def add(self, obj):
        self.session.add(obj)

    def delete(self, obj):
        self.session.delete(obj)

    def flush(self):
        self.session.flush()


class CRUDBase(Generic[ModelType, CreateSchemaType]):
    def __init__(self, model: type[ModelType]):
        self.model = model

    async def get(self, session: AsyncSession, id: Any) -> ModelType | None:
        return await session.get(self.model, id)

    async def get_by(self, session: AsyncSession, **kwargs: Any) -> ModelType | None:
        """
        灵活查询，适用于 unique 约束字段
        """
        statement = select(self.model).filter_by(**kwargs)
        result = await session.exec(statement)
        return result.first()

    async def get_multi(
        self,
        session: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "id",  # 保证分页确定性
    ) -> Sequence[ModelType]:
        # DBA 视角：大数据量下 offset 性能较差，后续可考虑 keyset pagination
        statement = (
            select(self.model)
            .offset(skip)
            .limit(limit)
            .order_by(col(getattr(self.model, sort_by)))
        )
        result = await session.exec(statement)
        return result.all()

    async def create(
        self, session: AsyncSession, *, obj_in: CreateSchemaType
    ) -> ModelType:
        db_obj = self.model.model_validate(obj_in)
        session.add(db_obj)
        # 注意：此处未处理并发冲突，实际业务中需 try/except IntegrityError
        await session.commit()
        await session.refresh(db_obj)
        return db_obj
