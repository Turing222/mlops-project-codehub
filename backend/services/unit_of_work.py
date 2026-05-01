"""SQLAlchemy UnitOfWork implementation.

职责：为一次业务事务创建共享 AsyncSession 和 repository 实例。
边界：本模块不包含业务规则；成功/异常时的提交回滚策略来自 AbstractUnitOfWork。
失败处理：无论提交或回滚是否成功，都必须关闭 session 释放连接。
"""

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.domain.interfaces import AbstractUnitOfWork
from backend.repositories.access_repo import AccessRepository
from backend.repositories.chat_repo import ChatRepository
from backend.repositories.knowledge_repo import KnowledgeRepository
from backend.repositories.task_repo import TaskRepository
from backend.repositories.user_repo import UserRepository


class SQLAlchemyUnitOfWork(AbstractUnitOfWork):
    """基于 SQLAlchemy AsyncSession 的 UnitOfWork。"""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        """返回当前事务 session；未进入上下文时抛出工程错误。"""
        if self._session is None:
            raise RuntimeError(
                "UnitOfWork session is not initialized. "
                "Did you forget to use 'async with uow'?"
            )
        return self._session

    async def __aenter__(self) -> "SQLAlchemyUnitOfWork":
        self._session = self.session_factory()

        # 同一个 UoW 周期内所有 repository 共享 session，确保事务一致。
        self.access_repo = AccessRepository(self._session)
        self.user_repo = UserRepository(self._session)
        self.chat_repo = ChatRepository(self._session)
        self.knowledge_repo = KnowledgeRepository(self._session)
        self.task_repo = TaskRepository(self._session)

        await super().__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """退出事务上下文并释放连接。"""
        try:
            await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            # close 放在 finally，避免异常路径泄漏连接池连接。
            if self._session:
                await self._session.close()
                self._session = None

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
