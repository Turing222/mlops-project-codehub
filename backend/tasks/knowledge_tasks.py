import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.core.config import settings
from backend.core.database import create_db_assets
from backend.core.task_broker import broker
from backend.services.chunking_service import ChunkingService
from backend.services.knowledge_service import KnowledgeService
from backend.services.task_service import TaskService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.services.vector_index_service import VectorIndexService
from backend.workflow.knowledge_rag_workflow import KnowledgeRAGWorkflow

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None
_embedder = None


def _get_session_factory() -> async_sessionmaker:
    global _engine, _session_factory
    if _session_factory is None:
        _engine, _session_factory = create_db_assets()
    return _session_factory


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = RAGEmbedderFactory.create(
            provider=settings.RAG_EMBED_PROVIDER,
            model_name=settings.RAG_EMBED_MODEL_NAME,
            device=settings.RAG_EMBED_DEVICE,
        )
    return _embedder


@broker.task(task_name="ingest_knowledge_file")
async def ingest_knowledge_file_task(file_id: str, task_id: str | None = None):
    file_uuid = uuid.UUID(file_id)
    task_uuid = uuid.UUID(task_id) if task_id else None

    logger.info("TaskIQ 开始处理知识库文件: file_id=%s task_id=%s", file_id, task_id)

    uow = SQLAlchemyUnitOfWork(_get_session_factory())
    task_service = TaskService(uow)
    chunking_service = ChunkingService(
        chunk_size=settings.KNOWLEDGE_CHUNK_SIZE,
        chunk_overlap=settings.KNOWLEDGE_CHUNK_OVERLAP,
    )
    vector_index_service = VectorIndexService(uow=uow, embedder=_get_embedder())
    knowledge_service = KnowledgeService(
        uow=uow,
        storage_root=settings.KNOWLEDGE_STORAGE_ROOT,
    )
    workflow = KnowledgeRAGWorkflow(
        knowledge_service=knowledge_service,
        chunking_service=chunking_service,
        vector_index_service=vector_index_service,
    )

    if task_uuid:
        await task_service.mark_processing(task_id=task_uuid, progress=5)

    try:
        await workflow.ingest_file(file_id=file_uuid)
        if task_uuid:
            await task_service.mark_completed(task_id=task_uuid, progress=100)
    except Exception as exc:
        if task_uuid:
            await task_service.mark_failed(task_id=task_uuid, error_log=str(exc))
        raise

    logger.info("TaskIQ 完成知识库文件处理: file_id=%s task_id=%s", file_id, task_id)
