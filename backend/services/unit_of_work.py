# app/services/unit_of_work.py
from backend.domain.interfaces import AbstractUnitOfWork
from backend.repositories.user_repo import UserRepository
from backend.repositories.chat_repo import ChatRepository
from backend.repositories.task_repo import TaskRepository

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession


class SQLAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory  # 注入工厂而非 session
        self.session: AsyncSession = None

    async def __aenter__(self):
        self.session = self.session_factory()  # 真正开启 Session
        self.users = UserRepository(self.session)  # 共享同一个 session
        self.chat_repo = ChatRepository(self.session)
        self.task = TaskRepository(self.session)
        return await super().__aenter__()

    async def __aexit__(self, *args):
        await super().__aexit__(*args)
        await self.session.close()  # 最终释放连接回池

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
