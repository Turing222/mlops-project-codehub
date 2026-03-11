import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO
from backend.repositories.chat_repo import ChatRepository
from backend.repositories.knowledge_repo import KnowledgeRepository
from backend.repositories.user_repo import UserRepository


class AbstractUnitOfWork(ABC):
    users: UserRepository
    chat_repo: ChatRepository
    knowledge: KnowledgeRepository

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


class AbstractRAGService(ABC):
    """RAG 检索服务抽象接口"""

    @abstractmethod
    async def retrieve(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
    ) -> list[dict]:
        """返回检索命中的上下文片段"""
        ...

    @abstractmethod
    async def retrieve_fulltext(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
    ) -> list[dict]:
        """返回全文检索命中的上下文片段"""
        ...

    @abstractmethod
    async def retrieve_hybrid(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
    ) -> list[dict]:
        """返回混合检索命中的上下文片段"""
        ...


class AbstractRAGEmbedder(ABC):
    """RAG 向量化器抽象接口"""

    @abstractmethod
    def encode_query(self, text: str) -> list[float]:
        """将查询文本编码为向量"""
        ...
