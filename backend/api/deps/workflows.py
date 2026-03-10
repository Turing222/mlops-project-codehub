from fastapi import Depends

from backend.api.deps.ai import (
    get_chunking_service,
    get_llm_service,
    get_rag_service,
    get_vector_index_service,
)
from backend.api.deps.services import get_knowledge_service
from backend.api.deps.uow import get_uow
from backend.domain.interfaces import (
    AbstractLLMService,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.services.chunking_service import ChunkingService
from backend.services.knowledge_service import KnowledgeService
from backend.services.vector_index_service import VectorIndexService
from backend.workflow.chat_workflow import ChatWorkflow
from backend.workflow.knowledge_rag_workflow import KnowledgeRAGWorkflow


def get_chat_workflow(
    uow: AbstractUnitOfWork = Depends(get_uow),
    llm_service: AbstractLLMService = Depends(get_llm_service),
    rag_service: AbstractRAGService = Depends(get_rag_service),
) -> ChatWorkflow:
    return ChatWorkflow(uow, llm_service, rag_service=rag_service)


def get_knowledge_rag_workflow(
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    chunking_service: ChunkingService = Depends(get_chunking_service),
    vector_index_service: VectorIndexService = Depends(get_vector_index_service),
) -> KnowledgeRAGWorkflow:
    return KnowledgeRAGWorkflow(
        knowledge_service=knowledge_service,
        chunking_service=chunking_service,
        vector_index_service=vector_index_service,
    )

