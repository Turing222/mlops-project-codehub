from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import get_settings

# echo=True 可以让你在控制台看到所有生成的原生 SQL，DBA 必备
settings = get_settings()
engine = create_async_engine(settings.database_url, echo=True)

# 定义 convention
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "%(table_name)s_pkey"
}

# 配置 metadata
SQLModel.metadata = MetaData(naming_convention=naming_convention)

# expire_on_commit=False 防止提交后对象过期导致的二次查询
async_session_maker = sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)


async def get_session():
    async with async_session_maker() as session:
        yield session