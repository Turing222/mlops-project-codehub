"""Knowledge ingestion TaskIQ tasks.

职责：在 worker 中装配知识库入库依赖，执行文件解析、切片和向量索引。
边界：上传请求只投递任务；实际解析和索引在本模块触发的 workflow 中完成。
失败处理：任务失败会尽力回写 TaskJob 状态，回写失败只记录日志并继续抛原错误。
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.config.llm import get_llm_model_config
from backend.core.config import settings
from backend.core.database import create_db_assets
from backend.core.exceptions import (
    AppException,
    app_service_error,
    app_validation_error,
)
from backend.core.task_broker import broker
from backend.core.trace_utils import set_span_attributes, trace_span, use_trace_context
from backend.domain.interfaces import AbstractRAGEmbedder
from backend.services.chunking_service import ChunkingService
from backend.services.knowledge_service import KnowledgeService
from backend.services.object_storage import ObjectStorage, create_object_storage
from backend.services.task_service import TaskService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.services.vector_index_service import VectorIndexService
from backend.workflow.knowledge_rag_workflow import KnowledgeRAGWorkflow

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None
_embedder: AbstractRAGEmbedder | None = None
_object_storage: ObjectStorage | None = None


def _get_session_factory() -> async_sessionmaker:
    global _engine, _session_factory
    if _session_factory is None:
        _engine, _session_factory = create_db_assets()
    return _session_factory


def _get_embedder() -> AbstractRAGEmbedder:
    global _embedder
    if _embedder is None:
        profile = get_llm_model_config().resolve_embedding_profile(
            settings.RAG_EMBED_PROVIDER
        )
        _embedder = RAGEmbedderFactory.create(
            provider=profile.provider,
            model_name=profile.model,
            base_url=profile.resolve_base_url(),
            api_key=profile.resolve_api_key(),
            dimensions=profile.dimensions,
        )
    return _embedder


def _get_object_storage() -> ObjectStorage:
    global _object_storage
    if _object_storage is None:
        _object_storage = create_object_storage(settings)
    return _object_storage


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
async def ingest_knowledge_file_task(
    file_id: str,
    task_id: str | None = None,
    trace_context: dict[str, str] | None = None,
) -> None:
    """TaskIQ 入口：恢复 trace context 后执行知识文件入库。"""
    with use_trace_context(trace_context):
        await _ingest_knowledge_file_task(file_id=file_id, task_id=task_id)


async def _ingest_knowledge_file_task(
    file_id: str,
    task_id: str | None = None,
) -> None:
    logger.info("TaskIQ 开始处理知识库文件: file_id=%s task_id=%s", file_id, task_id)
    embedding_profile = get_llm_model_config().resolve_embedding_profile(
        settings.RAG_EMBED_PROVIDER
    )

    with trace_span(
        "taskiq.knowledge.ingest.setup",
        {
            "rag.file_id": file_id,
            "task.id": task_id,
            "rag.embed.profile": embedding_profile.name,
            "rag.embed.provider": embedding_profile.provider,
            "rag.embed.model": embedding_profile.model,
        },
    ):
        uow = SQLAlchemyUnitOfWork(_get_session_factory())
        task_service = TaskService(uow)
        chunking_service = ChunkingService(
            chunk_size=settings.KNOWLEDGE_CHUNK_SIZE,
            chunk_overlap=settings.KNOWLEDGE_CHUNK_OVERLAP,
        )
        vector_index_service = VectorIndexService(
            uow=uow,
            embedder=_get_embedder(),
            embed_batch_size=settings.RAG_EMBED_BATCH_SIZE,
        )
        knowledge_service = KnowledgeService(
            uow=uow,
            storage=_get_object_storage(),
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

        with trace_span(
            "taskiq.knowledge.ingest.run",
            {"rag.file_id": file_uuid, "task.id": task_uuid},
        ) as span:
            if task_uuid:
                async with uow:
                    await task_service.mark_processing(task_id=task_uuid, progress=5)

            await workflow.ingest_file(file_id=file_uuid)
            if task_uuid:
                async with uow:
                    await task_service.mark_completed(task_id=task_uuid, progress=100)
            set_span_attributes(span, {"task.status": "completed"})
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
        raise app_validation_error(
            "任务参数非法: file_id/task_id 必须为 UUID",
            code="KNOWLEDGE_TASK_INVALID_ARGUMENT",
        ) from exc
    except AppException as exc:
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
        raise app_service_error(
            "知识文件处理失败，请稍后重试",
            code="KNOWLEDGE_FILE_INGEST_FAILED",
        ) from exc

    logger.info("TaskIQ 完成知识库文件处理: file_id=%s task_id=%s", file_id, task_id)
