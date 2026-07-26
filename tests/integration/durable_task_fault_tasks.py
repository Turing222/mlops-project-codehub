"""TaskIQ tasks used only by the disposable T1-4 fault matrix.

职责：用真实 Worker 进程执行 Chat/Knowledge claim，并提供可被 SIGKILL 的阻塞点。
边界：仅连接 fault-matrix 环境变量指定的 PostgreSQL/TaskIQ Redis；不调用 LLM、对象存储或外部 API。
副作用：更新可丢弃测试数据库、写测试队列/result key，并在阻塞任务中等待进程信号。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from backend.config.settings import settings
from backend.models.orm.chunk import DocumentChunk
from backend.models.orm.knowledge import FileStatus
from backend.models.schemas.chat.payloads import GenerationAttemptPayload
from backend.services.unit_of_work import SQLAlchemyUnitOfWork

FAULT_QUEUE_NAME = os.getenv("T1_4_FAULT_QUEUE", "taskiq_t1_4_fault")

FAULT_BROKER = ListQueueBroker(
    url=settings.taskiq_redis_url,
    queue_name=FAULT_QUEUE_NAME,
).with_result_backend(
    RedisAsyncResultBackend(
        redis_url=settings.taskiq_redis_url,
        result_ex_time=settings.TASKIQ_RESULT_TTL_SECONDS,
    )
)


def _new_uow() -> tuple[SQLAlchemyUnitOfWork, AsyncEngine]:
    engine = create_async_engine(
        settings.database_url,
        connect_args=settings.database_connect_args,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return SQLAlchemyUnitOfWork(session_factory), engine


async def _signal_ready(key: str, value: str) -> None:
    client = redis.from_url(settings.taskiq_redis_url, decode_responses=True)
    try:
        await client.set(key, value, ex=120)
    finally:
        await client.aclose()


@FAULT_BROKER.task(task_name="fault_chat_claim_and_block")
async def fault_chat_claim_and_block(
    *,
    user_id: str,
    session_id: str,
    assistant_message_id: str,
    generation_attempt: dict[str, object],
    ready_key: str,
) -> bool:
    """Claim one Chat attempt, commit its short lease, then block until killed."""
    attempt = GenerationAttemptPayload.model_validate(generation_attempt)
    uow, engine = _new_uow()
    try:
        now = datetime.now(UTC)
        async with uow:
            claimed = await uow.chat_repo.try_claim_generation_request(
                request_id=attempt.request_id,
                user_id=uuid.UUID(user_id),
                session_id=uuid.UUID(session_id),
                assistant_message_id=uuid.UUID(assistant_message_id),
                expected_attempt=attempt.attempt,
                task_id=attempt.task_id,
                lease_token=attempt.lease_token,
                started_at=now,
                lease_expires_at=now + timedelta(seconds=2),
            )
        if not claimed:
            return False
        await _signal_ready(ready_key, str(attempt.attempt))
        await asyncio.Event().wait()
        return True
    finally:
        await engine.dispose()


@FAULT_BROKER.task(task_name="fault_knowledge_claim_and_block")
async def fault_knowledge_claim_and_block(
    *,
    file_id: str,
    task_id: str,
    ready_key: str,
) -> bool:
    """Claim one Knowledge attempt, enter PARSING, then block until killed."""
    file_uuid = uuid.UUID(file_id)
    task_uuid = uuid.UUID(task_id)
    uow, engine = _new_uow()
    try:
        now = datetime.now(UTC)
        async with uow:
            attempt = await uow.task_repo.try_claim_kb_ingestion_task(
                task_id=task_uuid,
                file_id=file_uuid,
                claimed_at=now,
                lease_expires_at=now + timedelta(seconds=2),
            )
            if attempt is None:
                return False
            transitioned = await uow.knowledge_repo.try_transition_file_status(
                file_id=file_uuid,
                expected_previous_statuses=(FileStatus.UPLOADED,),
                target_status=FileStatus.PARSING,
            )
            if not transitioned:
                raise RuntimeError("fault Knowledge task could not enter PARSING")
        await _signal_ready(ready_key, str(attempt))
        await asyncio.Event().wait()
        return True
    finally:
        await engine.dispose()


@FAULT_BROKER.task(task_name="fault_knowledge_complete_once")
async def fault_knowledge_complete_once(
    *,
    file_id: str,
    task_id: str,
    business_count_key: str,
) -> bool:
    """Write one real chunk only when the durable Knowledge claim succeeds."""
    file_uuid = uuid.UUID(file_id)
    task_uuid = uuid.UUID(task_id)
    uow, engine = _new_uow()
    try:
        now = datetime.now(UTC)
        async with uow:
            attempt = await uow.task_repo.try_claim_kb_ingestion_task(
                task_id=task_uuid,
                file_id=file_uuid,
                claimed_at=now,
                lease_expires_at=now + timedelta(seconds=30),
            )
            if attempt is None:
                return False
            parsing = await uow.knowledge_repo.try_transition_file_status(
                file_id=file_uuid,
                expected_previous_statuses=(FileStatus.UPLOADED,),
                target_status=FileStatus.PARSING,
            )
            if not parsing:
                raise RuntimeError("fault Knowledge task could not enter PARSING")
            uow.session.add(
                DocumentChunk(
                    file_id=file_uuid,
                    message_id=None,
                    content="fault-matrix-chunk",
                    search_text="fault-matrix-chunk",
                    search_vector=None,
                    content_hash=uuid.uuid4().hex,
                    token_count=1,
                    chunk_index=0,
                    chunking_version=1,
                    meta_info={"fault_matrix": True},
                    embedding=[0.0] * 768,
                )
            )
            ready = await uow.knowledge_repo.try_transition_file_status(
                file_id=file_uuid,
                expected_previous_statuses=(FileStatus.PARSING,),
                target_status=FileStatus.READY,
            )
            completed = await uow.task_repo.try_complete_kb_ingestion_task(
                task_id=task_uuid,
                expected_attempt=attempt,
                finished_at=datetime.now(UTC),
            )
            if not ready or not completed:
                raise RuntimeError(
                    "fault Knowledge task could not commit terminal state"
                )

        client = redis.from_url(settings.taskiq_redis_url, decode_responses=True)
        try:
            await client.incr(business_count_key)
            await client.expire(business_count_key, 120)
        finally:
            await client.aclose()
        return True
    finally:
        await engine.dispose()
