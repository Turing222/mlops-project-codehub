from fastapi import Depends

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.api.deps.uow import get_uow
from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.contracts.interfaces import (
    AbstractLLMService,
    AbstractRAGEmbedder,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.services.chunking_service import ChunkingService
from backend.services.rag_service import RAGService
from backend.services.vector_index_service import VectorIndexService


def get_llm_service() -> AbstractLLMService:
    return LLMProviderFactory.create()


def get_rag_embedder() -> AbstractRAGEmbedder:
    profile = get_llm_model_config().resolve_embedding_profile(
        settings.RAG_EMBED_PROVIDER
    )
    return RAGEmbedderFactory.create(
        provider=profile.provider,
        model_name=profile.model,
        base_url=profile.resolve_base_url(),
        api_key=profile.resolve_api_key(),
        dimensions=profile.dimensions,
    )


def get_rag_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
    embedder: AbstractRAGEmbedder = Depends(get_rag_embedder),
) -> AbstractRAGService:
    return RAGService(uow=uow, embedder=embedder, top_k=settings.RAG_TOP_K)


def get_chunking_service() -> ChunkingService:
    return ChunkingService(
        chunk_size=settings.KNOWLEDGE_CHUNK_SIZE,
        chunk_overlap=settings.KNOWLEDGE_CHUNK_OVERLAP,
    )


def get_vector_index_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
    embedder: AbstractRAGEmbedder = Depends(get_rag_embedder),
) -> VectorIndexService:
    return VectorIndexService(
        uow=uow,
        embedder=embedder,
        embed_batch_size=settings.RAG_EMBED_BATCH_SIZE,
    )
