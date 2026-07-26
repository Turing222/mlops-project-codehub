"""Disposable end-to-end fault matrix for T1-4 durable task recovery.

职责：验证 Redis 全量重启、DB commit/enqueue 窗口、重复 delivery、Worker SIGKILL、
晚到 attempt 与恢复预算耗尽最终收敛到一个业务终态。
边界：只允许专用 runner 创建的 ``dewflow-t1-4-fault-*`` 容器；不连接外部 LLM/S3。
副作用：停止并重启专用 Redis 容器、强杀专用 TaskIQ Worker、写可丢弃 PostgreSQL。
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import redis.asyncio as redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from taskiq_redis import RedisAsyncResultBackend

from backend.application.chat.generation_recovery import (
    ChatGenerationRecoveryService,
)
from backend.application.chat.worker_persistence_handler import (
    GenerationAttemptRejected,
    WorkerPersistenceHandler,
)
from backend.application.knowledge.outbox_relay import KnowledgeOutboxRelayService
from backend.config.settings import settings
from backend.infra import task_dispatcher as dispatcher_module
from backend.infra.redis import RedisClient
from backend.infra.task_dispatcher import TaskDispatcher
from backend.models.enums import (
    ChatGenerationDispatchMode,
    ChatGenerationStatus,
    MessageStatus,
)
from backend.models.orm.chat import ChatMessage, ChatSession
from backend.models.orm.chunk import DocumentChunk
from backend.models.orm.credits import CreditAccount, CreditTransaction, UsageRecord
from backend.models.orm.knowledge import File, FileStatus, KnowledgeBase
from backend.models.orm.task import (
    KNOWLEDGE_INGESTION_EVENT,
    TaskOutboxStatus,
    TaskStatus,
)
from backend.models.orm.user import User
from backend.models.schemas.chat.payloads import (
    GenerationAttemptPayload,
    GenerationDispatchContext,
    GenerationPayload,
)
from backend.services.knowledge_ingestion_recovery_service import (
    KnowledgeIngestionRecoveryService,
)
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from tests.helpers.env import require_env
from tests.integration.durable_task_fault_tasks import (
    FAULT_BROKER,
    FAULT_QUEUE_NAME,
    fault_chat_claim_and_block,
    fault_knowledge_claim_and_block,
    fault_knowledge_complete_once,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.local_only,
    pytest.mark.requires_db,
    pytest.mark.requires_redis,
    pytest.mark.requires_taskiq,
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASKIQ_BIN = PROJECT_ROOT / ".venv" / "bin" / "taskiq"
FAULT_CONTAINER_PREFIX = "dewflow-t1-4-fault-"


@dataclass(slots=True)
class ChatSeed:
    user_id: uuid.UUID
    session_id: uuid.UUID
    assistant_message_id: uuid.UUID
    request_id: uuid.UUID
    attempt: GenerationAttemptPayload | None


@dataclass(slots=True)
class KnowledgeSeed:
    user_id: uuid.UUID
    kb_id: uuid.UUID
    file_id: uuid.UUID
    task_id: uuid.UUID
    outbox_id: uuid.UUID


@pytest.fixture(scope="module", autouse=True)
def require_disposable_fault_environment() -> None:
    if os.getenv("T1_4_FAULT_MATRIX") != "1":
        pytest.skip("run through scripts/qa/run_t1_4_fault_matrix.sh")
    if not TASKIQ_BIN.exists():
        pytest.skip(f"TaskIQ binary not found: {TASKIQ_BIN}")
    for env_name in (
        "T1_4_FAULT_CACHE_CONTAINER",
        "T1_4_FAULT_TASKIQ_CONTAINER",
    ):
        container_name = os.getenv(env_name, "")
        if not container_name.startswith(FAULT_CONTAINER_PREFIX):
            raise RuntimeError(
                f"{env_name} must name a disposable {FAULT_CONTAINER_PREFIX}* container"
            )


@pytest.fixture(autouse=True)
async def isolate_fault_broker_connection_pool() -> AsyncIterator[None]:
    """Keep TaskIQ's Redis pools bound to one pytest event loop at a time."""
    await FAULT_BROKER.startup()
    try:
        yield
    finally:
        await FAULT_BROKER.shutdown()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        require_env("TEST_DATABASE_URL"),
        connect_args=settings.database_connect_args,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _uow(factory: async_sessionmaker[AsyncSession]) -> SQLAlchemyUnitOfWork:
    return SQLAlchemyUnitOfWork(factory)


async def _seed_chat(
    factory: async_sessionmaker[AsyncSession],
    *,
    prepared: bool,
    with_credits: bool = False,
    now: datetime | None = None,
) -> ChatSeed:
    current_time = now or datetime.now(UTC)
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    uow = _uow(factory)
    async with uow:
        uow.session.add(
            User(
                id=user_id,
                username=f"fault-{user_id.hex}",
                email=f"{user_id.hex}@fault.invalid",
                is_active=True,
                max_tokens=100_000,
                used_tokens=0,
            )
        )
        uow.session.add(
            ChatSession(
                id=session_id,
                title="fault matrix",
                user_id=user_id,
                kb_id=None,
                workspace_id=None,
                llm_config={},
                context_state={},
                context_state_version=0,
            )
        )
        uow.session.add_all(
            [
                ChatMessage(
                    id=user_message_id,
                    session_id=session_id,
                    role="user",
                    content="fault question",
                    status=MessageStatus.SUCCESS,
                ),
                ChatMessage(
                    id=assistant_message_id,
                    session_id=session_id,
                    role="assistant",
                    content="",
                    status=MessageStatus.THINKING,
                ),
            ]
        )
        await uow.session.flush()
        request = await uow.chat_repo.create_generation_request(
            user_id=user_id,
            session_id=session_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            client_request_id=f"fault-{uuid.uuid4().hex}",
            dispatch_context=GenerationDispatchContext(
                mode=ChatGenerationDispatchMode.STREAM,
                generation_payload=GenerationPayload(
                    session_id=session_id,
                    query_text="fault question",
                ),
            ).model_dump(mode="json"),
            recovery_due_at=current_time - timedelta(seconds=1),
        )
        attempt = None
        if not prepared:
            attempt = GenerationAttemptPayload(
                request_id=request.id,
                attempt=1,
                task_id=f"fault-chat-{uuid.uuid4().hex}",
                lease_token=uuid.uuid4().hex,
            )
            queued = await uow.chat_repo.try_queue_generation_request(
                request_id=request.id,
                user_id=user_id,
                expected_attempt=1,
                task_id=attempt.task_id,
                lease_token=attempt.lease_token,
                queued_at=current_time,
                recovery_due_at=current_time + timedelta(seconds=30),
            )
            if not queued:
                raise RuntimeError("fault Chat request could not enter QUEUED")
        if with_credits:
            uow.session.add(CreditAccount(user_id=user_id, balance=100))

    return ChatSeed(
        user_id=user_id,
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        request_id=request.id,
        attempt=attempt,
    )


async def _seed_knowledge(
    factory: async_sessionmaker[AsyncSession],
    *,
    published_outbox: bool = False,
    now: datetime | None = None,
) -> KnowledgeSeed:
    current_time = now or datetime.now(UTC)
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    file_id = uuid.uuid4()
    uow = _uow(factory)
    async with uow:
        uow.session.add(
            User(
                id=user_id,
                username=f"fault-{user_id.hex}",
                email=f"{user_id.hex}@fault.invalid",
                is_active=True,
            )
        )
        uow.session.add(
            KnowledgeBase(
                id=kb_id,
                name="fault kb",
                description=None,
                user_id=user_id,
                workspace_id=None,
            )
        )
        uow.session.add(
            File(
                id=file_id,
                kb_id=kb_id,
                filename="fault.txt",
                file_path=f"fault/{file_id}.txt",
                storage_backend="local",
                file_size=10,
                status=FileStatus.UPLOADED,
                owner_id=user_id,
                workspace_id=None,
            )
        )
        await uow.session.flush()
        task = await uow.task_repo.create(
            action_type="KB_INGESTION",
            payload={"file_id": str(file_id), "kb_id": str(kb_id)},
            user_id=user_id,
            knowledge_file_id=file_id,
            knowledge_base_id=kb_id,
        )
        outbox = await uow.task_outbox_repo.create(
            task_id=task.id,
            event_type=KNOWLEDGE_INGESTION_EVENT,
            payload={
                "file_id": str(file_id),
                "task_id": str(task.id),
                "trace_context": None,
            },
            next_attempt_at=current_time,
        )
        if published_outbox:
            lease_owner = uuid.uuid4().hex
            claimed = await uow.task_outbox_repo.try_claim(
                outbox_id=outbox.id,
                due_at=current_time,
                lease_owner=lease_owner,
                lease_expires_at=current_time + timedelta(seconds=10),
                max_attempts=3,
            )
            if claimed is None:
                raise RuntimeError("fault Knowledge outbox could not be claimed")
            published = await uow.task_outbox_repo.try_mark_published(
                outbox_id=outbox.id,
                expected_attempt=claimed.attempt_count,
                lease_owner=lease_owner,
                published_at=current_time,
            )
            if not published:
                raise RuntimeError("fault Knowledge outbox could not be published")

    return KnowledgeSeed(
        user_id=user_id,
        kb_id=kb_id,
        file_id=file_id,
        task_id=task.id,
        outbox_id=outbox.id,
    )


def _start_fault_worker() -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            str(TASKIQ_BIN),
            "worker",
            "tests.integration.durable_task_fault_tasks:FAULT_BROKER",
            "tests.integration.durable_task_fault_tasks",
            "--workers",
            "1",
        ],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


async def _stop_worker(
    process: subprocess.Popen[str],
    *,
    force: bool,
) -> None:
    if process.poll() is not None:
        return
    process_group = os.getpgid(process.pid)
    os.killpg(process_group, signal.SIGKILL if force else signal.SIGTERM)
    try:
        await asyncio.to_thread(process.wait, 10)
    except subprocess.TimeoutExpired:
        os.killpg(process_group, signal.SIGKILL)
        await asyncio.to_thread(process.wait, 5)


async def _wait_for_redis_value(client: redis.Redis, key: str, expected: str) -> None:
    for _ in range(150):
        if await client.get(key) == expected:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"timed out waiting for Redis key {key}")


async def _docker(action: str, *container_names: str) -> None:
    for name in container_names:
        if not name.startswith(FAULT_CONTAINER_PREFIX):
            raise RuntimeError(f"refusing to control non-fault container: {name}")
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", action, *container_names],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker {action} failed: {result.stdout.strip()} {result.stderr.strip()}"
        )


async def _wait_for_redis_restart() -> None:
    for url in (require_env("TEST_REDIS_URL"), require_env("TEST_TASKIQ_REDIS_URL")):
        client = redis.from_url(url)
        try:
            for _ in range(100):
                try:
                    if await client.ping():
                        break
                except RedisError:
                    await asyncio.sleep(0.1)
                    continue
                await asyncio.sleep(0.1)
            else:
                raise AssertionError(f"Redis did not recover: {url}")
        finally:
            await client.aclose()


async def test_db_commit_and_full_redis_restart_converge_with_bounded_recovery(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    chat = await _seed_chat(session_factory, prepared=True, now=now)
    knowledge = await _seed_knowledge(session_factory, now=now)
    queue_name = f"taskiq_fault_restart_{uuid.uuid4().hex}"
    monkeypatch.setattr(dispatcher_module, "TASKIQ_QUEUE_NAME", queue_name)
    cache_container = os.environ["T1_4_FAULT_CACHE_CONTAINER"]
    taskiq_container = os.environ["T1_4_FAULT_TASKIQ_CONTAINER"]

    task_client = redis.from_url(require_env("TEST_TASKIQ_REDIS_URL"))
    await task_client.delete(queue_name)
    await _docker("stop", cache_container, taskiq_container)
    try:
        dispatcher = TaskDispatcher(task_client)
        chat_result = await ChatGenerationRecoveryService(
            uow=_uow(session_factory),
            dispatcher=dispatcher,
            recovery_seconds=1,
            max_dispatch_attempts=3,
            batch_size=10,
        ).reconcile_due_requests(now=now)
        knowledge_result = await KnowledgeOutboxRelayService(
            uow=_uow(session_factory),
            dispatcher=dispatcher,
            retry_seconds=1,
            lease_seconds=1,
            max_attempts=3,
            batch_size=10,
        ).relay_due(now=now)
        assert chat_result.dispatch_error_count == 1
        assert knowledge_result.retry_count == 1
    finally:
        await task_client.aclose()
        await _docker("start", cache_container, taskiq_container)
        await _wait_for_redis_restart()

    task_client = redis.from_url(require_env("TEST_TASKIQ_REDIS_URL"))
    try:
        dispatcher = TaskDispatcher(task_client)
        recovered_at = now + timedelta(seconds=2)
        chat_result = await ChatGenerationRecoveryService(
            uow=_uow(session_factory),
            dispatcher=dispatcher,
            recovery_seconds=1,
            max_dispatch_attempts=3,
            batch_size=10,
        ).reconcile_due_requests(now=recovered_at)
        knowledge_result = await KnowledgeOutboxRelayService(
            uow=_uow(session_factory),
            dispatcher=dispatcher,
            retry_seconds=1,
            lease_seconds=1,
            max_attempts=3,
            batch_size=10,
        ).relay_due(now=recovered_at)
        assert chat_result.queued_redispatched_count == 1
        assert knowledge_result.published_count == 1

        messages = [
            json.loads(raw) for raw in await task_client.lrange(queue_name, 0, -1)
        ]
        async with _uow(session_factory).read_context() as uow:
            current_chat = await uow.chat_repo.get_generation_request_for_actor(
                request_id=chat.request_id,
                user_id=chat.user_id,
            )
            current_outbox = await uow.task_outbox_repo.get(knowledge.outbox_id)
        assert current_chat is not None
        assert current_chat.status == ChatGenerationStatus.QUEUED
        assert current_chat.dispatch_attempts == 2
        assert current_outbox is not None
        assert TaskOutboxStatus(current_outbox.status) == TaskOutboxStatus.PUBLISHED
        assert {message["task_id"] for message in messages} == {
            current_chat.task_id,
            str(knowledge.outbox_id),
        }

        await task_client.delete(queue_name)
        third_result = await ChatGenerationRecoveryService(
            uow=_uow(session_factory),
            dispatcher=dispatcher,
            recovery_seconds=1,
            max_dispatch_attempts=3,
            batch_size=10,
        ).reconcile_due_requests(now=now + timedelta(seconds=4))
        assert third_result.queued_redispatched_count == 1
        await task_client.delete(queue_name)

        exhausted_result = await ChatGenerationRecoveryService(
            uow=_uow(session_factory),
            dispatcher=dispatcher,
            recovery_seconds=1,
            max_dispatch_attempts=3,
            batch_size=10,
        ).reconcile_due_requests(now=now + timedelta(seconds=6))
        assert exhausted_result.failed_count == 1

        async with _uow(session_factory) as uow:
            final_chat = await uow.chat_repo.get_generation_request_for_actor(
                request_id=chat.request_id,
                user_id=chat.user_id,
            )
            final_message = await uow.chat_repo.get_message(chat.assistant_message_id)
            assert final_chat is not None
            assert final_chat.status == ChatGenerationStatus.FAILED
            assert final_chat.dispatch_attempts == 3
            assert final_chat.error_code == "CHAT_DISPATCH_RETRY_EXHAUSTED"
            assert final_message is not None
            assert final_message.status == MessageStatus.FAILED
            late_claim = await uow.chat_repo.try_claim_generation_request(
                request_id=chat.request_id,
                user_id=chat.user_id,
                session_id=chat.session_id,
                assistant_message_id=chat.assistant_message_id,
                expected_attempt=final_chat.attempt,
                task_id=final_chat.task_id or "missing",
                lease_token=final_chat.lease_token or "missing",
                started_at=now + timedelta(seconds=7),
                lease_expires_at=now + timedelta(seconds=30),
            )
            assert not late_claim
    finally:
        await task_client.delete(queue_name)
        await task_client.aclose()


async def test_sigkill_chat_worker_fences_late_terminal_without_settlement(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chat = await _seed_chat(session_factory, prepared=False)
    assert chat.attempt is not None
    ready_key = f"fault:chat-ready:{uuid.uuid4().hex}"
    task_client = redis.from_url(
        require_env("TEST_TASKIQ_REDIS_URL"), decode_responses=True
    )
    await task_client.delete(FAULT_QUEUE_NAME, ready_key)
    worker = _start_fault_worker()
    task = None
    try:
        task = await fault_chat_claim_and_block.kiq(
            user_id=str(chat.user_id),
            session_id=str(chat.session_id),
            assistant_message_id=str(chat.assistant_message_id),
            generation_attempt=chat.attempt.model_dump(mode="json"),
            ready_key=ready_key,
        )
        await _wait_for_redis_value(task_client, ready_key, "1")
        await _stop_worker(worker, force=True)

        recovered_at = datetime.now(UTC) + timedelta(seconds=10)
        result = await ChatGenerationRecoveryService(
            uow=_uow(session_factory),
            dispatcher=TaskDispatcher(task_client),
            recovery_seconds=1,
            max_dispatch_attempts=3,
            batch_size=10,
        ).reconcile_due_requests(now=recovered_at)
        assert result.failed_count == 1

        async with _uow(session_factory) as uow:
            final = await uow.chat_repo.get_generation_request_for_actor(
                request_id=chat.request_id,
                user_id=chat.user_id,
            )
            assert final is not None
            assert final.status == ChatGenerationStatus.FAILED
            assert final.error_code == "CHAT_GENERATION_LEASE_EXPIRED"
            late_terminal = await uow.chat_repo.try_finalize_generation_request(
                request_id=chat.request_id,
                expected_attempt=chat.attempt.attempt,
                lease_token=chat.attempt.lease_token,
                target_status=ChatGenerationStatus.SUCCEEDED,
                finished_at=recovered_at + timedelta(seconds=1),
            )
            assert not late_terminal
            usage_count = await uow.session.scalar(
                select(func.count())
                .select_from(UsageRecord)
                .where(UsageRecord.user_id == chat.user_id)
            )
            assert usage_count == 0
    finally:
        await _stop_worker(worker, force=True)
        await task_client.delete(FAULT_QUEUE_NAME, ready_key)
        if task is not None:
            await task_client.delete(task.task_id)
        await task_client.aclose()


async def test_duplicate_chat_terminal_settles_credits_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chat = await _seed_chat(session_factory, prepared=False, with_credits=True)
    assert chat.attempt is not None
    now = datetime.now(UTC)
    async with _uow(session_factory) as uow:
        claimed = await uow.chat_repo.try_claim_generation_request(
            request_id=chat.request_id,
            user_id=chat.user_id,
            session_id=chat.session_id,
            assistant_message_id=chat.assistant_message_id,
            expected_attempt=chat.attempt.attempt,
            task_id=chat.attempt.task_id,
            lease_token=chat.attempt.lease_token,
            started_at=now,
            lease_expires_at=now + timedelta(seconds=30),
        )
        assert claimed

    handler = WorkerPersistenceHandler(
        uow=_uow(session_factory),
        redis_client=RedisClient(),
    )
    await handler.persist_success(
        assistant_message_id=chat.assistant_message_id,
        user_id=chat.user_id,
        content="first terminal answer",
        tokens_input=1000,
        tokens_output=0,
        search_context=None,
        start_time=time.time(),
        generation_attempt=chat.attempt,
    )
    with pytest.raises(GenerationAttemptRejected):
        await handler.persist_success(
            assistant_message_id=chat.assistant_message_id,
            user_id=chat.user_id,
            content="duplicate terminal answer",
            tokens_input=1000,
            tokens_output=0,
            search_context=None,
            start_time=time.time(),
            generation_attempt=chat.attempt,
        )

    async with _uow(session_factory).read_context() as uow:
        account = await uow.credit_repo.get_account(chat.user_id)
        assert account is not None
        message = await uow.chat_repo.get_message(chat.assistant_message_id)
        request = await uow.chat_repo.get_generation_request_for_actor(
            request_id=chat.request_id,
            user_id=chat.user_id,
        )
        tx_count = await uow.session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.account_id == account.id)
        )
        usage_count = await uow.session.scalar(
            select(func.count())
            .select_from(UsageRecord)
            .where(UsageRecord.chat_message_id == chat.assistant_message_id)
        )
    assert account.balance == 99
    assert tx_count == 1
    assert usage_count == 1
    assert message is not None
    assert message.content == "first terminal answer"
    assert request is not None
    assert request.status == ChatGenerationStatus.SUCCEEDED


async def test_sigkill_knowledge_worker_replays_the_same_durable_job(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge = await _seed_knowledge(session_factory, published_outbox=True)
    ready_key = f"fault:knowledge-ready:{uuid.uuid4().hex}"
    recovery_queue = f"taskiq_fault_knowledge_recovery_{uuid.uuid4().hex}"
    monkeypatch.setattr(dispatcher_module, "TASKIQ_QUEUE_NAME", recovery_queue)
    task_client = redis.from_url(
        require_env("TEST_TASKIQ_REDIS_URL"), decode_responses=True
    )
    await task_client.delete(FAULT_QUEUE_NAME, recovery_queue, ready_key)
    worker = _start_fault_worker()
    task = None
    try:
        task = await fault_knowledge_claim_and_block.kiq(
            file_id=str(knowledge.file_id),
            task_id=str(knowledge.task_id),
            ready_key=ready_key,
        )
        await _wait_for_redis_value(task_client, ready_key, "1")
        await _stop_worker(worker, force=True)

        recovered_at = datetime.now(UTC) + timedelta(seconds=10)
        result = await KnowledgeIngestionRecoveryService(
            _uow(session_factory),
            stale_timeout_seconds=1,
            max_ingestion_attempts=3,
            max_publish_attempts=3,
            batch_size=10,
        ).recover_stale_ingestions(now=recovered_at)
        assert result.retried_task_count == 1

        async with _uow(session_factory) as uow:
            current_task = await uow.task_repo.get(knowledge.task_id)
            current_file = await uow.knowledge_repo.get_file(knowledge.file_id)
            current_outbox = await uow.task_outbox_repo.get(knowledge.outbox_id)
            assert current_task is not None
            assert TaskStatus(current_task.status) == TaskStatus.PENDING
            assert current_task.attempt_count == 1
            assert current_file is not None
            assert FileStatus(current_file.status) == FileStatus.UPLOADED
            assert current_outbox is not None
            assert TaskOutboxStatus(current_outbox.status) == TaskOutboxStatus.PENDING
            late_terminal = await uow.task_repo.try_complete_kb_ingestion_task(
                task_id=knowledge.task_id,
                expected_attempt=1,
                finished_at=recovered_at + timedelta(seconds=1),
            )
            assert not late_terminal

        relay_result = await KnowledgeOutboxRelayService(
            uow=_uow(session_factory),
            dispatcher=TaskDispatcher(task_client),
            retry_seconds=1,
            lease_seconds=1,
            max_attempts=3,
            batch_size=10,
        ).publish_one(
            outbox_id=knowledge.outbox_id,
            now=recovered_at + timedelta(seconds=1),
        )
        assert relay_result.published_count == 1
        raw_message = await task_client.lindex(recovery_queue, 0)
        assert raw_message is not None
        message = json.loads(raw_message)
        assert message["task_id"] == str(knowledge.outbox_id)
        assert message["args"][1] == str(knowledge.task_id)
    finally:
        await _stop_worker(worker, force=True)
        await task_client.delete(FAULT_QUEUE_NAME, recovery_queue, ready_key)
        if task is not None:
            await task_client.delete(task.task_id)
        await task_client.aclose()


async def test_duplicate_knowledge_delivery_writes_one_chunk_and_one_terminal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    knowledge = await _seed_knowledge(session_factory)
    business_count_key = f"fault:knowledge-writes:{uuid.uuid4().hex}"
    task_client = redis.from_url(
        require_env("TEST_TASKIQ_REDIS_URL"), decode_responses=True
    )
    await task_client.delete(FAULT_QUEUE_NAME, business_count_key)
    worker = _start_fault_worker()
    first = None
    second = None
    try:
        first = await fault_knowledge_complete_once.kiq(
            file_id=str(knowledge.file_id),
            task_id=str(knowledge.task_id),
            business_count_key=business_count_key,
        )
        second = await fault_knowledge_complete_once.kiq(
            file_id=str(knowledge.file_id),
            task_id=str(knowledge.task_id),
            business_count_key=business_count_key,
        )
        first_result = await first.wait_result(timeout=20)
        second_result = await second.wait_result(timeout=20)
        assert [first_result.return_value, second_result.return_value].count(True) == 1
        await _wait_for_redis_value(task_client, business_count_key, "1")

        async with _uow(session_factory).read_context() as uow:
            task = await uow.task_repo.get(knowledge.task_id)
            file_obj = await uow.knowledge_repo.get_file(knowledge.file_id)
            chunk_count = await uow.session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.file_id == knowledge.file_id)
            )
        assert task is not None
        assert TaskStatus(task.status) == TaskStatus.COMPLETED
        assert task.attempt_count == 1
        assert file_obj is not None
        assert FileStatus(file_obj.status) == FileStatus.READY
        assert chunk_count == 1
    finally:
        await _stop_worker(worker, force=False)
        await task_client.delete(FAULT_QUEUE_NAME, business_count_key)
        for task in (first, second):
            if task is not None:
                await task_client.delete(task.task_id)
        await task_client.aclose()


def test_fault_broker_uses_the_isolated_taskiq_endpoint() -> None:
    result_backend = FAULT_BROKER.result_backend
    assert isinstance(result_backend, RedisAsyncResultBackend)
    assert result_backend.result_ex_time == settings.TASKIQ_RESULT_TTL_SECONDS
