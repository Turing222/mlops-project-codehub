from collections.abc import AsyncGenerator

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
    "pk": "%(table_name)s_pkey",
}

# 配置 metadata
SQLModel.metadata = MetaData(naming_convention=naming_convention)

# expire_on_commit=False 防止提交后对象过期导致的二次查询
async_session_maker = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    仅负责 Session 的生命周期管理（创建与关闭）。
    不负责事务的 commit/rollback，这部分交由 Service 层或装饰器处理。
    """
    # async_session_maker 应该在你的 config 或 database 文件里定义好了
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            # 只有在 Session 本身出错时这里才需要处理
            # 具体的业务事务回滚应该在装饰器里做
            await session.rollback()
            raise
        finally:
            # async with 会自动调用 session.close()，这里不需要手动写
            pass
