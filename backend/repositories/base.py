from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase[ModelType, CreateSchemaType: BaseModel, UpdateSchemaType: BaseModel]:
    def __init__(self, model: type[ModelType], session: AsyncSession):
        """
        CRUD 对象应该包含具体的 SQLAlchemy 模型 (Model class)
        例如: user_crud = CRUDBase(User)
        """
        self.model = model
        self.session = session

    # -----------------------------------------------------------
    # 1. GET (Read One): 根据主键 ID 查询单条记录
    # -----------------------------------------------------------
    async def get(self, id: Any) -> ModelType | None:
        """
        根据 ID 获取单个对象。
        如果找不到，返回 None。
        """
        # SQLAlchemy 1.4/2.0 风格: session.get(Model, id)
        return await self.session.get(self.model, id)

    # -----------------------------------------------------------
    # 2. GET (Read One): 根据查询条件灵活查询
    # -----------------------------------------------------------
    async def get_by(self, **kwargs: Any) -> ModelType | None:
        """
        灵活查询，适用于 unique 约束字段
        """
        statement = select(self.model).filter_by(**kwargs)
        result = await self.session.exec(statement)
        return result.scalars().first()

    # -----------------------------------------------------------
    # 3. GET MULTI (Read Many): 查询列表（通常带分页）
    # -----------------------------------------------------------
    async def get_multi(
        self, *, skip: int = 0, limit: int = 100
    ) -> Sequence[ModelType] | None:
        """
        获取对象列表。
        skip: 跳过前 N 条 (offset)
        limit: 限制返回条数 (limit)
        """
        # 构造查询语句: SELECT * FROM table LIMIT 100 OFFSET 0
        stmt = select(self.model).offset(skip).limit(limit)

        # 执行查询
        result = await self.session.exec(stmt)

        # scalars().all() 会把结果解包成模型对象列表
        return result.scalars().all()

    # -----------------------------------------------------------
    # 4. CREATE: 创建新记录
    # -----------------------------------------------------------
    async def create(self, *, obj_in: CreateSchemaType | dict[str, Any]) -> ModelType:
        """
        创建新对象。
        接受 Pydantic Schema 或 字典。
        """
        # 1. 数据转换：如果是 Pydantic 对象，转为字典
        # jsonable_encoder 可以处理一些特殊类型（如 datetime 转 str），
        # 但通常直接用 obj_in.model_dump() 也是可以的，看你的需求。
        # 简单场景直接用 obj_in_data = obj_in.dict() (v1) 或 model_dump() (v2) 即可。
        if isinstance(obj_in, dict):
            create_data = obj_in
        else:
            create_data = obj_in.model_dump()

        # 2. 实例化 SQLAlchemy 模型
        # 等同于: db_obj = User(name="...", age=...)
        # 这里用 **create_data 语法糖解包字典
        db_obj = self.model(**create_data)

        # 3. 添加到 Session 并提交
        self.session.add(db_obj)
        await self.session.flush()  # flush 获取 ID，但不提交事务
        await self.session.refresh(
            db_obj
        )  # 如果数据库有默认值生成（如 created_at），需要 refresh 拿回来

        return db_obj

    # -----------------------------------------------------------
    # 5. UPDATE: (你之前提供的那个，为了完整性我放这里)
    # -----------------------------------------------------------
    async def update(
        self,
        *,
        db_obj: ModelType,
        obj_in: UpdateSchemaType | dict[str, Any],
    ) -> ModelType:
        """
        修改对象。
        接受 Pydantic Schema 或 字典。
        """
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    # -----------------------------------------------------------
    # 6. DELETE: 删除记录
    # -----------------------------------------------------------
    async def remove(self, *, id: Any) -> ModelType | None:
        """
        根据 ID 删除对象。
        通常返回被删除的对象（以便前端确认删了谁），或者是 None。
        """
        # 1. 先查出来，确保存在
        obj = await self.session.get(self.model, id)
        if obj:
            # 2. 标记删除
            await self.session.delete(obj)
            # 3. 执行
            await self.session.flush()
        return obj
