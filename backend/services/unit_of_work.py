"""SQLAlchemy UnitOfWork implementation.

职责：为一次业务事务创建共享 AsyncSession 和 repository 实例。
边界：本模块不包含业务规则；成功/异常时的提交回滚策略来自 AbstractUnitOfWork。
失败处理：无论提交或回滚是否成功，都必须关闭 session 释放连接。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.repositories.access_repo import AccessRepository
from backend.repositories.audit_repo import AuditRepository
from backend.repositories.chat_repo import ChatRepository
from backend.repositories.credit_repo import CreditRepository
from backend.repositories.knowledge_repo import KnowledgeRepository
from backend.repositories.repo_analysis_repo import RepoAnalysisRepository
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
        self._bind_repositories(self._session)

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

    @asynccontextmanager
    async def savepoint(self) -> AsyncIterator["SQLAlchemyUnitOfWork"]:
        """Create a nested transaction (SAVEPOINT) for partial rollback."""
        if self._session is None:
            raise RuntimeError("UnitOfWork session is not initialized.")
        async with self._session.begin_nested():
            yield self

    @asynccontextmanager
    async def read_context(self) -> AsyncIterator["SQLAlchemyUnitOfWork"]:
        """创建只读 UoW 上下文；正常退出不提交事务。"""
        if self._session is not None:
            raise RuntimeError("Cannot open read_context inside an active UoW")
        self._session = self.session_factory()
        self._bind_repositories(self._session)
        try:
            yield self
        except Exception:
            await self.rollback()
            raise
        finally:
            if self._session:
                await self._session.close()
                self._session = None

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    def _bind_repositories(self, session: AsyncSession) -> None:
        # 同一个 UoW 周期内所有 repository 共享 session，确保事务一致。
        self.access_repo = AccessRepository(session)
        self.audit_repo = AuditRepository(session)
        self.user_repo = UserRepository(session)
        self.chat_repo = ChatRepository(session)
        self.knowledge_repo = KnowledgeRepository(session)
        self.task_repo = TaskRepository(session)
        self.repo_analysis_repo = RepoAnalysisRepository(session)
        self.credit_repo = CreditRepository(session)
