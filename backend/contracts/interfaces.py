import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any

from backend.contracts.repository_protocols import (
    AccessRepositoryProtocol,
    AuditRepositoryProtocol,
    ChatRepositoryProtocol,
    CreditRepositoryProtocol,
    KnowledgeRepositoryProtocol,
    RepoAnalysisRepositoryProtocol,
    TaskRepositoryProtocol,
    UserRepositoryProtocol,
)
from backend.models.schemas.chat.dto import LLMQueryDTO, LLMResultDTO
from backend.models.schemas.chat.payloads import GenerationResult


class AbstractUnitOfWork(ABC):
    access_repo: AccessRepositoryProtocol
    audit_repo: AuditRepositoryProtocol
    user_repo: UserRepositoryProtocol
    chat_repo: ChatRepositoryProtocol
    knowledge_repo: KnowledgeRepositoryProtocol
    task_repo: TaskRepositoryProtocol
    repo_analysis_repo: RepoAnalysisRepositoryProtocol
    credit_repo: CreditRepositoryProtocol

    async def __aenter__(self) -> "AbstractUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

    @abstractmethod
    def savepoint(self) -> AbstractAsyncContextManager["AbstractUnitOfWork"]: ...

    @abstractmethod
    def read_context(self) -> AbstractAsyncContextManager["AbstractUnitOfWork"]: ...


class AbstractLLMService(ABC):
    """
    LLM 服务抽象接口
    与具体的 LLM 提供商解耦 (OpenAI, Claude, Local LLM...)
    """

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

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

    async def close(self) -> None:  # noqa: B027 — optional hook with default no-op
        """可选：释放底层 HTTP client / 连接池资源。默认无操作。"""


class AbstractRerankService(ABC):
    """Rerank 服务抽象接口。"""

    @abstractmethod
    async def rerank(
        self,
        *,
        query_text: str,
        documents: list[str],
        top_k: int,
    ) -> list[tuple[int, float]]:
        """返回 0-based 文档索引与相关性分数，按相关性降序排列。"""
        ...

    async def close(self) -> None:  # noqa: B027 — optional hook with default no-op
        """可选：释放底层 HTTP client / 连接池资源。默认无操作。"""


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

    @abstractmethod
    async def retrieve_with_rerank(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
        candidate_count: int | None = None,
    ) -> list[dict]:
        """返回经过可选 LLM 重排序的上下文片段"""
        ...

    @abstractmethod
    async def rerank(
        self,
        query_text: str,
        candidates: list[dict],
        top_k: int | None = None,
    ) -> list[dict]:
        """对已检索候选片段进行 LLM 重排序"""
        ...


class AbstractRAGEmbedder(ABC):
    """RAG 向量化器抽象接口"""

    DEFAULT_ENCODE_DOCUMENTS_CONCURRENCY = 8

    def __init__(self) -> None:
        self._encode_semaphore: asyncio.Semaphore | None = None

    @abstractmethod
    async def encode_query(self, text: str) -> list[float]:
        """将查询文本编码为向量"""
        ...

    async def encode_document(self, text: str) -> list[float]:
        """将文档片段编码为向量；默认复用查询编码。"""
        return await self.encode_query(text)

    async def encode_documents(self, texts: list[str]) -> list[list[float]]:
        """将文档片段批量编码为向量；默认有界并发编码。"""
        if self._encode_semaphore is None:
            self._encode_semaphore = asyncio.Semaphore(
                self.DEFAULT_ENCODE_DOCUMENTS_CONCURRENCY
            )
        semaphore = self._encode_semaphore  # type narrow for async with

        async def encode_with_limit(text: str) -> list[float]:
            async with semaphore:
                return await self.encode_document(text)

        return await asyncio.gather(*(encode_with_limit(text) for text in texts))

    async def close(self) -> None:  # noqa: B027 — optional hook with default no-op
        """可选：释放底层 HTTP client / 连接池资源。默认无操作。"""


class AbstractExternalContextProvider(ABC):
    """外部上下文检索抽象接口"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier for metrics and tracing."""
        ...

    @abstractmethod
    async def search(self, *, query_text: str, top_k: int) -> list[Any]:
        """Return provider-neutral chunks for the query."""
        ...

    async def close(self) -> None:  # noqa: B027 — optional hook with default no-op
        """可选：释放底层 HTTP client / 连接池资源。默认无操作。"""


class AbstractTaskDispatcher(ABC):
    """Web → Worker 任务投递抽象。

    所有 TaskIQ .kiq() 调用收敛到该接口的实现端，
    Web workflow 只依赖此 Protocol，不直接 import worker.tasks.*。
    """

    @abstractmethod
    async def enqueue_stream(
        self,
        generation_payload: dict[str, Any],
        channel: str,
        trace_context: dict[str, str] | None = None,
        assistant_message_id: str | None = None,
        user_id: str | None = None,
        idempotency_lock_key: str | None = None,
    ) -> None:
        """投递流式 LLM 生成任务到 TaskIQ worker。"""
        ...

    @abstractmethod
    async def enqueue_nonstream(
        self,
        generation_payload: dict[str, Any],
        trace_context: dict[str, str] | None = None,
        assistant_message_id: str | None = None,
        user_id: str | None = None,
        idempotency_lock_key: str | None = None,
    ) -> GenerationResult:
        """投递非流式 LLM 生成任务并等待结果返回。"""
        ...

    @abstractmethod
    async def enqueue_ingestion(
        self,
        file_id: str,
        task_id: str | None = None,
        trace_context: dict[str, str] | None = None,
    ) -> None:
        """投递知识库文件入库任务到 TaskIQ worker。"""
        ...

    @abstractmethod
    async def enqueue_repo_analysis(
        self,
        run_id: str,
        task_id: str,
        trace_context: dict[str, str] | None = None,
    ) -> None:
        """投递 GitHub repo README 初筛任务到 TaskIQ worker。"""
        ...
