import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.core.config import settings
from backend.core.database import create_db_assets
from backend.core.exceptions import AppError, ServiceError, ValidationError
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
            base_url=settings.RAG_EMBED_BASE_URL,
            api_key=settings.RAG_EMBED_API_KEY,
            dimensions=settings.RAG_EMBED_DIM,
        )
    return _embedder


async def _safe_mark_failed(
    *,
    uow: SQLAlchemyUnitOfWork,
    task_service: TaskService,
    task_id: uuid.UUID | None,
    error_log: str,
) -> None:
    if task_id is None:
        return
    try:
        async with uow:
            await task_service.mark_failed(task_id=task_id, error_log=error_log)
    except Exception:
        logger.exception("TaskIQ 任务失败状态回写异常: task_id=%s", task_id)


@broker.task(task_name="ingest_knowledge_file")
async def ingest_knowledge_file_task(file_id: str, task_id: str | None = None):
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
        max_upload_size_mb=settings.KNOWLEDGE_MAX_UPLOAD_SIZE_MB,
    )
    workflow = KnowledgeRAGWorkflow(
        knowledge_service=knowledge_service,
        chunking_service=chunking_service,
        vector_index_service=vector_index_service,
    )

    task_uuid: uuid.UUID | None = None
    try:
        file_uuid = uuid.UUID(file_id)
        task_uuid = uuid.UUID(task_id) if task_id else None

        if task_uuid:
            async with uow:
                await task_service.mark_processing(task_id=task_uuid, progress=5)

        await workflow.ingest_file(file_id=file_uuid)
        if task_uuid:
            async with uow:
                await task_service.mark_completed(task_id=task_uuid, progress=100)
    except ValueError as exc:
        logger.warning(
            "TaskIQ 知识库任务参数非法: file_id=%s task_id=%s",
            file_id,
            task_id,
        )
        await _safe_mark_failed(
            uow=uow,
            task_service=task_service,
            task_id=task_uuid,
            error_log="任务参数非法: file_id/task_id 必须为 UUID",
        )
        raise ValidationError("任务参数非法: file_id/task_id 必须为 UUID") from exc
    except AppError as exc:
        await _safe_mark_failed(
            uow=uow,
            task_service=task_service,
            task_id=task_uuid,
            error_log=str(exc),
        )
        logger.warning(
            "TaskIQ 知识库任务业务失败: file_id=%s task_id=%s error=%s",
            file_id,
            task_id,
            exc,
        )
        raise
    except Exception as exc:
        await _safe_mark_failed(
            uow=uow,
            task_service=task_service,
            task_id=task_uuid,
            error_log="知识文件处理失败，请稍后重试",
        )
        logger.exception(
            "TaskIQ 知识库任务系统异常: file_id=%s task_id=%s",
            file_id,
            task_id,
        )
        raise ServiceError("知识文件处理失败，请稍后重试") from exc

    logger.info("TaskIQ 完成知识库文件处理: file_id=%s task_id=%s", file_id, task_id)
