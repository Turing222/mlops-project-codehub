"""Knowledge ingestion TaskIQ tasks.

职责：在 worker 中装配知识库入库依赖，执行文件解析、切片和向量索引。
边界：上传请求只投递任务；实际解析和索引在本模块触发的 workflow 中完成。
失败处理：任务失败会尽力回写 TaskJob 状态，回写失败只记录日志并继续抛原错误。
"""

import logging
import uuid
from dataclasses import asdict

from backend.application.knowledge.ingestion_heartbeat import IngestionLeaseHeartbeat
from backend.application.knowledge.ingestion_workflow import KnowledgeRAGWorkflow
from backend.application.knowledge.outbox_relay import KnowledgeOutboxRelayService
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.core.exceptions import (
    AppException,
    app_service_error,
    app_validation_error,
)
from backend.infra.redis import redis_client
from backend.infra.task_broker import broker
from backend.infra.task_dispatcher import TaskDispatcher
from backend.models.orm.task import TaskStatus
from backend.observability.trace_utils import (
    set_span_attributes,
    trace_span,
    use_trace_context,
)
from backend.services.chunking_service import ChunkingService
from backend.services.knowledge_ingestion_recovery_service import (
    KnowledgeIngestionRecoveryService,
)
from backend.services.knowledge_service import KnowledgeService
from backend.services.permission_service import PermissionService
from backend.services.task_service import TaskService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.services.vector_index_service import VectorIndexService
from backend.worker.dependencies import (
    get_worker_embedder,
    get_worker_object_storage,
    get_worker_session_factory,
)

logger = logging.getLogger(__name__)


async def safe_mark_failed(
    *,
    uow: SQLAlchemyUnitOfWork,
    task_service: TaskService,
    task_id: uuid.UUID | None,
    expected_attempt: int | None,
    error_log: str,
) -> None:
    if task_id is None or expected_attempt is None:
        return
    try:
        async with uow:
            await task_service.fail_kb_ingestion(
                task_id=task_id,
                expected_attempt=expected_attempt,
                expected_statuses=(TaskStatus.PROCESSING,),
                error_log=error_log,
            )
    except Exception:
        logger.exception("TaskIQ 任务失败状态回写异常: task_id=%s", task_id)


@broker.task(task_name="ingest_knowledge_file")
async def ingest_knowledge_file_task(
    file_id: str,
    task_id: str | None = None,
    trace_context: dict[str, str] | None = None,
    outbox_id: str | None = None,
) -> None:
    """TaskIQ 入口：恢复 trace context 后执行知识文件入库。"""
    with use_trace_context(trace_context):
        await _ingest_knowledge_file_task(
            file_id=file_id,
            task_id=task_id,
            outbox_id=outbox_id,
        )


@broker.task(
    task_name="recover_stale_knowledge_ingestions",
    schedule=[
        {
            "cron": "*/15 * * * *",
            "schedule_id": "recover_stale_knowledge_ingestions_every_15m",
        }
    ],
)
async def recover_stale_knowledge_ingestions_task() -> dict[str, int]:
    """TaskIQ 入口：逐对收敛 Knowledge File/Task/Outbox 状态。"""
    uow = SQLAlchemyUnitOfWork(get_worker_session_factory())
    service = KnowledgeIngestionRecoveryService(uow)
    with trace_span("taskiq.knowledge.recover_stale_ingestions", {}) as span:
        result = await service.recover_stale_ingestions()
        set_span_attributes(
            span,
            {
                "knowledge.recovery.scanned_task_count": result.scanned_task_count,
                "knowledge.recovery.created_outbox_count": (
                    result.created_outbox_count
                ),
                "knowledge.recovery.retried_task_count": result.retried_task_count,
                "knowledge.recovery.completed_task_count": (
                    result.completed_task_count
                ),
                "knowledge.recovery.failed_file_count": result.failed_file_count,
                "knowledge.recovery.failed_task_count": result.failed_task_count,
                "knowledge.recovery.conflict_count": result.conflict_count,
            },
        )
    return asdict(result)


@broker.task(
    task_name="relay_knowledge_ingestion_outbox",
    schedule=[
        {
            "cron": "* * * * *",
            "schedule_id": "relay_knowledge_ingestion_outbox_every_minute",
        }
    ],
)
async def relay_knowledge_ingestion_outbox_task() -> dict[str, int]:
    """TaskIQ 入口：发布一批到期 Knowledge outbox 事件。"""
    redis_connection = await redis_client.init()
    service = KnowledgeOutboxRelayService(
        uow=SQLAlchemyUnitOfWork(get_worker_session_factory()),
        dispatcher=TaskDispatcher(redis_connection),
    )
    with trace_span("taskiq.knowledge.relay_outbox", {}) as span:
        result = await service.relay_due()
        set_span_attributes(
            span,
            {
                "knowledge.outbox.claimed_count": result.claimed_count,
                "knowledge.outbox.published_count": result.published_count,
                "knowledge.outbox.retry_count": result.retry_count,
                "knowledge.outbox.dead_count": result.dead_count,
                "knowledge.outbox.conflict_count": result.conflict_count,
            },
        )
    return asdict(result)


async def _ingest_knowledge_file_task(
    file_id: str,
    task_id: str | None = None,
    outbox_id: str | None = None,
) -> None:
    logger.info("TaskIQ 开始处理知识库文件: file_id=%s task_id=%s", file_id, task_id)
    embedding_profile = get_llm_model_config().resolve_embedding_profile(
        ai_settings.RAG_EMBED_PROVIDER
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
        uow = SQLAlchemyUnitOfWork(get_worker_session_factory())
        task_service = TaskService(uow)
        chunking_service = ChunkingService(
            chunk_size=ai_settings.KNOWLEDGE_CHUNK_SIZE,
            chunk_overlap=ai_settings.KNOWLEDGE_CHUNK_OVERLAP,
        )
        vector_index_service = VectorIndexService(
            uow=uow,
            embedder=get_worker_embedder(),
            embed_batch_size=ai_settings.RAG_EMBED_BATCH_SIZE,
            read_uow_factory=lambda: SQLAlchemyUnitOfWork(get_worker_session_factory()),
        )
        knowledge_service = KnowledgeService(
            uow=uow,
            storage=get_worker_object_storage(),
            max_upload_size_mb=ai_settings.KNOWLEDGE_MAX_UPLOAD_SIZE_MB,
            permission_service=PermissionService(uow),
        )
        workflow = KnowledgeRAGWorkflow(
            knowledge_service=knowledge_service,
            chunking_service=chunking_service,
            vector_index_service=vector_index_service,
            task_service=task_service,
        )

    task_uuid: uuid.UUID | None = None
    claimed_attempt: int | None = None
    try:
        file_uuid = uuid.UUID(file_id)
        if task_id is None:
            raise ValueError("task_id is required")
        task_uuid = uuid.UUID(task_id)
        if outbox_id is not None:
            uuid.UUID(outbox_id)

        with trace_span(
            "taskiq.knowledge.ingest.run",
            {"rag.file_id": file_uuid, "task.id": task_uuid},
        ) as span:
            async with uow:
                claimed_attempt = await task_service.claim_kb_ingestion(
                    task_id=task_uuid,
                    file_id=file_uuid,
                )
            if claimed_attempt is None:
                if await _is_duplicate_delivery(
                    uow=uow,
                    task_id=task_uuid,
                    file_id=file_uuid,
                ):
                    logger.info(
                        "Knowledge duplicate delivery acknowledged",
                        extra={
                            "event": "knowledge_ingestion_duplicate_delivery",
                            "file_id": str(file_uuid),
                            "task_id": str(task_uuid),
                            "outbox_id": outbox_id,
                        },
                    )
                    return
                raise app_validation_error(
                    "知识入库任务身份或状态无效",
                    code="KNOWLEDGE_TASK_CLAIM_REJECTED",
                )

            heartbeat = IngestionLeaseHeartbeat(
                uow_factory=lambda: SQLAlchemyUnitOfWork(get_worker_session_factory()),
                task_id=task_uuid,
                expected_attempt=claimed_attempt,
            )
            if not await heartbeat.start():
                raise app_validation_error(
                    "知识入库任务租约已失效",
                    code="KNOWLEDGE_TASK_LEASE_LOST",
                )
            try:
                await workflow.ingest_file(
                    file_id=file_uuid,
                    task_id=task_uuid,
                    expected_attempt=claimed_attempt,
                )
            finally:
                await heartbeat.stop()

            async with uow:
                completed = await task_service.complete_kb_ingestion(
                    task_id=task_uuid,
                    expected_attempt=claimed_attempt,
                )
            if not completed and not await _task_is_completed(
                uow=uow,
                task_id=task_uuid,
            ):
                raise app_validation_error(
                    "知识入库任务终态提交被租约拒绝",
                    code="KNOWLEDGE_TASK_TERMINAL_REJECTED",
                )
            set_span_attributes(span, {"task.status": "completed"})
    except ValueError as exc:
        logger.warning(
            "TaskIQ 知识库任务参数非法: file_id=%s task_id=%s",
            file_id,
            task_id,
        )
        await safe_mark_failed(
            uow=uow,
            task_service=task_service,
            task_id=task_uuid,
            expected_attempt=claimed_attempt,
            error_log="任务参数非法: file_id/task_id 必须为 UUID",
        )
        raise app_validation_error(
            "任务参数非法: file_id/task_id 必须为 UUID",
            code="KNOWLEDGE_TASK_INVALID_ARGUMENT",
        ) from exc
    except AppException as exc:
        await safe_mark_failed(
            uow=uow,
            task_service=task_service,
            task_id=task_uuid,
            expected_attempt=claimed_attempt,
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
        await safe_mark_failed(
            uow=uow,
            task_service=task_service,
            task_id=task_uuid,
            expected_attempt=claimed_attempt,
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


async def _is_duplicate_delivery(
    *,
    uow: SQLAlchemyUnitOfWork,
    task_id: uuid.UUID,
    file_id: uuid.UUID,
) -> bool:
    async with uow.read_context():
        task = await uow.task_repo.get(task_id)
    if task is None:
        return False
    return (
        task.action_type == "KB_INGESTION"
        and task.knowledge_file_id == file_id
        and TaskStatus(task.status)
        in {
            TaskStatus.PROCESSING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELED,
        }
    )


async def _task_is_completed(
    *,
    uow: SQLAlchemyUnitOfWork,
    task_id: uuid.UUID,
) -> bool:
    async with uow.read_context():
        task = await uow.task_repo.get(task_id)
    return task is not None and TaskStatus(task.status) == TaskStatus.COMPLETED
