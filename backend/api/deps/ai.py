from fastapi import Depends

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.api.deps.uow import get_uow
from backend.core.config import settings
from backend.domain.interfaces import (
    AbstractLLMService,
    AbstractRAGEmbedder,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.services.chunking_service import ChunkingService
from backend.services.rag_service import RAGService
from backend.services.vector_index_service import VectorIndexService


def get_llm_service() -> AbstractLLMService:
    return LLMProviderFactory.create(provider=settings.LLM_PROVIDER)


def get_rag_embedder() -> AbstractRAGEmbedder:
    return RAGEmbedderFactory.create(
        provider=settings.RAG_EMBED_PROVIDER,
        model_name=settings.RAG_EMBED_MODEL_NAME,
        base_url=settings.RAG_EMBED_BASE_URL,
        api_key=settings.RAG_EMBED_API_KEY,
        dimensions=settings.RAG_EMBED_DIM,
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
    return VectorIndexService(uow=uow, embedder=embedder)
