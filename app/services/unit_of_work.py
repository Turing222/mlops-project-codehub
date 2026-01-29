# app/services/unit_of_work.py
from app.domain.interfaces import AbstractUnitOfWork
from app.repositories.user_repo import UserRepository


class SQLAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session_factory):
        self.session_factory = session_factory  # 注入工厂而非 session

    async def __aenter__(self):
        self.session = self.session_factory()  # 真正开启 Session
        self.users = UserRepository(self.session)  # 共享同一个 session
        return await super().__aenter__()

    async def __aexit__(self, *args):
        await super().__aexit__(*args)
        await self.session.close()  # 最终释放连接回池

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
