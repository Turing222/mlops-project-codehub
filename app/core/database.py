from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

# echo=True 可以让你在控制台看到所有生成的原生 SQL，DBA 必备
settings = get_settings()
engine = create_async_engine(settings.database_url, echo=True)


# expire_on_commit=False 防止提交后对象过期导致的二次查询
async_session_maker = sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)


async def get_session():
    async with async_session_maker() as session:
        yield session