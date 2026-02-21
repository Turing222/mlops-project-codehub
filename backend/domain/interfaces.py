from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO
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


class AbstractLLMService(ABC):
    """
    LLM 服务抽象接口
    与具体的 LLM 提供商解耦 (OpenAI, Claude, Local LLM...)
    """

    @abstractmethod
    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        """流式返回响应"""
        if False:
            yield ""

    @abstractmethod
    async def generate_response(
        self,
        query: LLMQueryDTO,
    ) -> LLMResultDTO:
        """完整返回响应"""
        ...
