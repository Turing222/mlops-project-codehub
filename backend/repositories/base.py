"""Generic CRUD base for SQLAlchemy repositories.

职责：提供基于泛型的增删改查模板方法，封装 session 生命周期内的 flush/refresh。
边界：本模块不绑定任何具体 ORM 模型，所有方法通过 TypeVar 保持类型安全。
"""

from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase[ModelType, CreateSchemaType: BaseModel, UpdateSchemaType: BaseModel]:
    """泛型 CRUD 模板，子类通过组合而非继承使用。"""

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get(self, id: Any) -> ModelType | None:
        stmt = select(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by(self, **kwargs: Any) -> ModelType | None:
        statement = select(self.model).filter_by(**kwargs)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_multi(
        self, *, skip: int = 0, limit: int = 100
    ) -> Sequence[ModelType]:
        stmt = select(self.model).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create(self, *, obj_in: CreateSchemaType | dict[str, Any]) -> ModelType:
        create_data = obj_in if isinstance(obj_in, dict) else obj_in.model_dump()

        db_obj = self.model(**create_data)

        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)

        return db_obj

    async def update(
        self,
        *,
        db_obj: ModelType,
        obj_in: UpdateSchemaType | dict[str, Any],
    ) -> ModelType:
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        unknown_fields = [field for field in update_data if not hasattr(db_obj, field)]
        if unknown_fields:
            field_text = ", ".join(sorted(unknown_fields))
            raise ValueError(
                f"Unknown fields for {type(db_obj).__name__} update: {field_text}"
            )

        for field, value in update_data.items():
            setattr(db_obj, field, value)

        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def remove(self, *, id: Any) -> ModelType | None:
        obj = await self.session.get(self.model, id)
        if obj:
            await self.session.delete(obj)
            await self.session.flush()
        return obj
