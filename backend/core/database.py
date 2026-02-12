from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.core.config import get_settings

# echo=True 可以让你在控制台看到所有生成的原生 SQL，DBA 必备
settings = get_settings()
engine = create_async_engine(
    settings.database_url, echo=True, pool_size=10, max_overflow=20
)


# expire_on_commit=False 防止提交后对象过期导致的二次查询
async_session_maker = async_sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False
)
