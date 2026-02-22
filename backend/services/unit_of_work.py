from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.domain.interfaces import AbstractUnitOfWork
from backend.repositories.chat_repo import ChatRepository
from backend.repositories.task_repo import TaskRepository
from backend.repositories.user_repo import UserRepository


class SQLAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory
        # 显式使用私有变量，表达"初始状态为 None"
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        """
        核心优化：通过 Property 消除业务逻辑中的 if 判断。
        如果 session 没初始化，直接在访问时抛出明确的工程错误。
        """
        if self._session is None:
            raise RuntimeError(
                "UnitOfWork session is not initialized. "
                "Did you forget to use 'async with uow'?"
            )
        return self._session

    async def __aenter__(self):
        # 1. 开启真正的数据库连接
        self._session = self.session_factory()

        # 2. 注入 Session 到 Repository，确保整个 UoW 周期内共享同一个事务
        # 注意：这里直接传私有变量或 property 均可，此时已确保不为 None
        self.users = UserRepository(self._session)
        self.chat_repo = ChatRepository(self._session)
        self.task = TaskRepository(self._session)

        return await super().__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        健壮性保证：无论是否发生异常，都确保资源正确释放。
        """
        try:
            if exc_type:
                # 如果代码块内发生异常，自动回滚
                await self.rollback()
            else:
                # 如果一切正常，自动提交（可选，也可以由 Service 层显式调用）
                await self.commit()
            await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            # 无论提交/回滚是否成功，必须关闭 Session 释放连接回池（DBA 核心关注点）
            if self._session:
                await self._session.close()
                self._session = None  # 重置状态，防止 UoW 实例被非法复用

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
