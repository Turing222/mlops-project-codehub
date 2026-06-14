"""Worker-only dependency assembly.

职责：为 TaskIQ worker 进程缓存重量级依赖，并装配 workflow 所需服务。
边界：Web/FastAPI 依赖仍由 backend.api.deps 提供；本模块只服务 worker。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.ai.providers.rerank.factory import RerankProviderFactory
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.contracts.interfaces import (
    AbstractExternalContextProvider,
    AbstractLLMService,
    AbstractRAGEmbedder,
    AbstractRAGService,
    AbstractRerankService,
)
from backend.infra.database import create_db_assets
from backend.services.external_context_service import (
    create_external_context_provider,
)
from backend.services.object_storage import ObjectStorage, create_object_storage
from backend.services.rag_planning_service import RAGPlanningService
from backend.services.rag_service import RAGService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.services.vector_index_service import VectorIndexService

logger = logging.getLogger(__name__)


class WorkerContainer:
    """Cache worker dependencies and release process-scoped resources."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None
        self._llm_service: AbstractLLMService | None = None
        self._llm_services_by_provider: dict[str, AbstractLLMService] = {}
        self._llm_service_errors_by_provider: dict[str, Exception] = {}
        self._embedder: AbstractRAGEmbedder | None = None
        self._rerank_service: AbstractRerankService | None = None
        self._rerank_init_failed = False
        self._rag_service: AbstractRAGService | None = None
        self._rag_planning_service: RAGPlanningService | None = None
        self._external_context_provider: AbstractExternalContextProvider | None = None
        self._object_storage: ObjectStorage | None = None

    def get_session_factory(self) -> async_sessionmaker:
        """Return the cached worker SQLAlchemy session factory."""
        if self._session_factory is None:
            self._engine, self._session_factory = create_db_assets()
        return self._session_factory

    def get_llm_service(self) -> AbstractLLMService:
        """Return the cached worker LLM service."""
        if self._llm_service is None:
            self._llm_service = LLMProviderFactory.create()
        return self._llm_service

    def get_llm_service_for_provider(
        self,
        provider: str | None,
    ) -> AbstractLLMService:
        """Return a cached worker LLM service for an explicit provider/profile."""
        if provider is None:
            return self.get_llm_service()
        if provider in self._llm_service_errors_by_provider:
            raise self._llm_service_errors_by_provider[provider]
        if provider not in self._llm_services_by_provider:
            try:
                self._llm_services_by_provider[provider] = LLMProviderFactory.create(
                    provider
                )
            except Exception as exc:
                self._llm_service_errors_by_provider[provider] = exc
                raise
        return self._llm_services_by_provider[provider]

    def get_embedder(self) -> AbstractRAGEmbedder:
        """Return the cached worker RAG embedder."""
        if self._embedder is None:
            profile = get_llm_model_config().resolve_embedding_profile(
                ai_settings.RAG_EMBED_PROVIDER
            )
            self._embedder = RAGEmbedderFactory.create(
                provider=profile.provider,
                model_name=profile.model,
                base_url=profile.resolve_base_url(),
                api_key=profile.resolve_api_key(),
                dimensions=profile.dimensions,
            )
        return self._embedder

    def get_rerank_service(self) -> AbstractRerankService | None:
        """Return the cached worker-side rerank service when configured.

        Degrade to no rerank when provider initialization fails so generation
        tasks keep running, matching the web path and RAG call-layer fallback.
        """
        if self._rerank_init_failed:
            return None
        if self._rerank_service is None:
            provider = (ai_settings.RAG_RERANK_PROVIDER or "").strip()
            if not provider or provider.lower() == "mock":
                return None
            if provider:
                try:
                    config = get_llm_model_config()
                    if config.rerank_profiles:
                        profile = config.resolve_rerank_profile(provider)
                        self._rerank_service = RerankProviderFactory.create(
                            profile=profile
                        )
                    else:
                        self._rerank_service = RerankProviderFactory.create(provider)
                except Exception as exc:
                    logger.warning(
                        "Worker rerank initialization degraded; rerank disabled for this worker process",
                        extra={
                            "event": "worker_rerank_init_degraded",
                            "rerank_provider": provider,
                            "degradation_mode": "disabled",
                            "error": str(exc),
                        },
                    )
                    self._rerank_init_failed = True
                    return None
        return self._rerank_service

    def get_rag_service(self) -> AbstractRAGService:
        """Return the cached worker-side RAG service for generation context retrieval."""
        if self._rag_service is None:
            reranker = self.get_rerank_service()
            session_factory = self.get_session_factory()
            uow = SQLAlchemyUnitOfWork(session_factory)
            embedder = self.get_embedder()
            vector_index_service = VectorIndexService(
                uow=uow,
                embedder=embedder,
                embed_batch_size=ai_settings.RAG_EMBED_BATCH_SIZE,
                read_uow_factory=lambda: SQLAlchemyUnitOfWork(session_factory),
            )
            rerank_score_kind = "bifrost_rerank"
            config = get_llm_model_config()
            if (
                reranker is not None
                and config.rerank_profiles
                and ai_settings.RAG_RERANK_PROVIDER
            ):
                profile = config.resolve_rerank_profile(ai_settings.RAG_RERANK_PROVIDER)
                rerank_score_kind = profile.effective_score_kind()
            self._rag_service = RAGService(
                embedder=embedder,
                vector_index_service=vector_index_service,
                top_k=ai_settings.RAG_TOP_K,
                reranker=reranker,
                rerank_candidate_count=ai_settings.RAG_RERANK_CANDIDATE_COUNT,
                rerank_top_k=ai_settings.RAG_RERANK_TOP_K,
                rerank_score_kind=rerank_score_kind,
            )
        return self._rag_service

    def get_rag_planning_service(self) -> RAGPlanningService:
        """Return the cached worker-side RAG planning service."""
        if self._rag_planning_service is None:
            self._rag_planning_service = RAGPlanningService(
                provider=ai_settings.RAG_PLANNER_PROVIDER
            )
        return self._rag_planning_service

    def get_external_context_provider(self) -> AbstractExternalContextProvider | None:
        """Return the cached worker-side external context provider."""
        if self._external_context_provider is None:
            self._external_context_provider = create_external_context_provider(
                always_create=True
            )
        return self._external_context_provider

    def get_object_storage(self) -> ObjectStorage:
        """Return the cached worker object storage adapter."""
        if self._object_storage is None:
            self._object_storage = create_object_storage(settings)
        return self._object_storage

    async def close(self) -> None:
        """Release cached resources owned by this worker process."""
        if self._llm_service is not None:
            await self._llm_service.close()
        for service in self._llm_services_by_provider.values():
            if service is not self._llm_service:
                await service.close()
        if self._embedder is not None:
            await self._embedder.close()
        if self._external_context_provider is not None:
            await self._external_context_provider.close()
        if self._rerank_service is not None:
            await self._rerank_service.close()
        if self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        self._session_factory = None
        self._rag_service = None
        self._llm_service = None
        self._llm_services_by_provider = {}
        self._llm_service_errors_by_provider = {}
        self._embedder = None
        self._rerank_service = None
        self._rerank_init_failed = False
        self._rag_planning_service = None
        self._external_context_provider = None
        self._object_storage = None


_container: WorkerContainer | None = None


def get_worker_container() -> WorkerContainer:
    """Return the process-scoped worker dependency container."""
    global _container
    if _container is None:
        _container = WorkerContainer()
    return _container


def set_worker_container(container: WorkerContainer | None) -> None:
    """Replace the worker container for tests or lifecycle reset."""
    global _container
    _container = container


async def close_worker_container() -> None:
    """Close and clear the process-scoped worker dependency container."""
    global _container
    if _container is not None:
        await _container.close()
        _container = None


def get_worker_session_factory() -> async_sessionmaker:
    """Return the cached worker SQLAlchemy session factory."""
    return get_worker_container().get_session_factory()


def get_worker_llm_service() -> AbstractLLMService:
    """Return the cached worker LLM service."""
    return get_worker_container().get_llm_service()


def get_worker_llm_service_for_provider(
    provider: str | None,
) -> AbstractLLMService:
    """Return the cached worker LLM service for an explicit provider/profile."""
    return get_worker_container().get_llm_service_for_provider(provider)


def get_worker_embedder() -> AbstractRAGEmbedder:
    """Return the cached worker RAG embedder."""
    return get_worker_container().get_embedder()


def get_worker_rag_service() -> AbstractRAGService:
    """Return the cached worker-side RAG service for generation context retrieval."""
    return get_worker_container().get_rag_service()


def get_worker_rag_planning_service() -> RAGPlanningService:
    """Return the cached worker-side RAG planning service."""
    return get_worker_container().get_rag_planning_service()


def get_worker_external_context_provider() -> AbstractExternalContextProvider | None:
    """Return the cached worker-side external context provider."""
    return get_worker_container().get_external_context_provider()


def get_worker_object_storage() -> ObjectStorage:
    """Return the cached worker object storage adapter."""
    return get_worker_container().get_object_storage()
