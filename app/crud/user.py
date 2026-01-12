# app/crud/user.py
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import insert, select

from app.models.user import User


# 1. 查询：带分页的 Read
async def get_users(
        session: AsyncSession, 
        skip: int = 0, 
        limit: int = 10,
        username: str = None):
    statement = select(User).offset(skip).limit(limit)
    if username:
        # 增加过滤条件
        statement = statement.where(User.username == username)

    result = await session.execute(statement)
    return result.scalars().all()


# 2. 批量插入：带冲突处理 (Upsert)
async def upsert_users(session: AsyncSession, user_maps: list[dict]):
    if not user_maps:
        return
    """
    DBA 视角：这会生成 INSERT ... ON CONFLICT (email) DO UPDATE ...
    """
    for mapping in user_maps:
        stmt = pg_insert(User).values(mapping)
        # 假设 email 是唯一键，如果冲突了，就更新最后登录时间
        stmt = stmt.on_conflict_do_update(
            index_elements=['email'],
            set_=dict(username=mapping['username'])
        )
        await session.execute(stmt) 
    await session.commit()


async def create_user(username: str, email: str, session: AsyncSession):
    db_user = User(username=username, email=email)
    session.add(db_user)
    await session.commit()
    session.refresh(db_user)



    
async def get_existing_usernames(session: AsyncSession, usernames: list[str]) -> set[str]:
    """
    输入一个用户名列表，返回数据库中已经存在的用户名集合。
    使用 Core 风格，性能高。
    """
    if not usernames:
        return set()

    # 这里的 select(User.username) 就是 Core 风格
    # 它只查询 username 字段，不会把整行数据都查出来
    stmt = select(User.username).where(User.username.in_(usernames))
    
    result = await session.execute(stmt)
    
    # scalars().all() 会返回一个列表 ['zhangsan', 'lisi', ...]
    # 转成 set 方便后续 O(1) 复杂度的查找比对
    return set(result.scalars().all())