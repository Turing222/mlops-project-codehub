"""Scheduled Chat generation recovery tasks.

职责：装配 recovery service、数据库 UoW 与 fire-and-forget dispatcher。
边界：TaskIQ task 只触发有界扫描；恢复规则由 application service 持有。
副作用：读取/更新 PostgreSQL，并可能向 task broker 补发 Chat 任务。
"""

from dataclasses import asdict

from backend.application.chat.generation_recovery import (
    ChatGenerationRecoveryService,
)
from backend.infra.redis import redis_client
from backend.infra.task_broker import broker
from backend.infra.task_dispatcher import TaskDispatcher
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.worker.dependencies import get_worker_session_factory


@broker.task(
    task_name="reconcile_chat_generations",
    schedule=[
        {
            "cron": "* * * * *",
            "schedule_id": "reconcile_chat_generations_every_minute",
        }
    ],
)
async def reconcile_chat_generations_task() -> dict[str, int]:
    """Scan and converge one bounded batch of due Chat requests."""
    redis_connection = await redis_client.init()
    service = ChatGenerationRecoveryService(
        uow=SQLAlchemyUnitOfWork(get_worker_session_factory()),
        dispatcher=TaskDispatcher(redis_connection),
    )
    with trace_span("taskiq.chat.reconcile_generations", {}) as span:
        result = await service.reconcile_due_requests()
        set_span_attributes(
            span,
            {
                "chat.recovery.scanned_count": result.scanned_count,
                "chat.recovery.prepared_dispatched_count": (
                    result.prepared_dispatched_count
                ),
                "chat.recovery.queued_redispatched_count": (
                    result.queued_redispatched_count
                ),
                "chat.recovery.failed_count": result.failed_count,
                "chat.recovery.conflict_count": result.conflict_count,
                "chat.recovery.dispatch_error_count": result.dispatch_error_count,
            },
        )
    return asdict(result)
