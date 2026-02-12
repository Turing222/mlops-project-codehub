from abc import ABC, abstractmethod

from backend.repositories.chat_repo import ChatRepository
from backend.repositories.user_repo import UserRepository


class AbstractUnitOfWork(ABC):
    users: UserRepository
    chat_repo: ChatRepository

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    @abstractmethod
    async def commit(self): ...
    @abstractmethod
    async def rollback(self): ...
