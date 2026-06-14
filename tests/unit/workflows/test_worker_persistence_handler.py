"""Worker persistence handler tests — token billing and failure persistence.

职责：验证 WorkerPersistenceHandler 的成功持久化（token 计费、幂等锁更新）和失败持久化
（Redis 锁清理、消息状态写入）；边界：不启动 HTTP stack 或真实 Redis；副作用：无。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.exceptions import AppException
from backend.models.orm.chat import MessageStatus

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_persistence_uow() -> AsyncMock:
    from contextlib import asynccontextmanager

    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.user_repo = AsyncMock()
    uow.chat_repo = AsyncMock()
    uow.chat_repo.get_message = AsyncMock(return_value=None)
    uow.chat_repo.update_message_status = AsyncMock()

    # Mock credit_repo
    uow.credit_repo = AsyncMock()
    credit_account = MagicMock()
    credit_account.balance = 1000
    uow.credit_repo.get_account_with_lock = AsyncMock(return_value=credit_account)
    uow.credit_repo.create_account = AsyncMock(return_value=credit_account)
    uow.credit_repo.get_transaction_by_idempotency_key = AsyncMock(return_value=None)
    uow.credit_repo.get_usage_record_by_chat_message_id = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _noop_savepoint():
        yield uow

    uow.savepoint = _noop_savepoint
    return uow


@pytest.fixture
def fake_persistence_redis() -> AsyncMock:
    redis_client = AsyncMock()
    redis_client.init = AsyncMock()
    return redis_client


async def test_persist_success_token_limit_exceeded_writes_failed(
    fake_persistence_uow, fake_persistence_redis
) -> None:
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    handler = WorkerPersistenceHandler(
        uow=fake_persistence_uow, redis_client=fake_persistence_redis
    )

    assistant_message_id = uuid.uuid4()

    with patch(
        "backend.application.chat.worker_persistence_handler.CreditService.spend_for_model_usage",
        new_callable=AsyncMock,
        side_effect=AppException(
            message="Credits 余额不足",
            code="INSUFFICIENT_CREDITS",
            status_code=400,
        ),
    ):
        await handler.persist_success(
            assistant_message_id=assistant_message_id,
            user_id=uuid.uuid4(),
            content="some content",
            tokens_input=100,
            tokens_output=50,
            search_context=None,
            start_time=0.0,
        )

    fake_persistence_uow.chat_repo.update_message_status.assert_awaited_once()
    call_kwargs = fake_persistence_uow.chat_repo.update_message_status.call_args.kwargs
    assert call_kwargs["status"] == MessageStatus.FAILED
    assert (
        call_kwargs["content"]
        == "Credits 余额不足，本次生成未记录。已生成的内容不会被扣费，请签到后再试。"
    )
    assert call_kwargs["message_metadata"]["response_outcome"] == "failed"


async def test_persist_success_assistant_message_id_none_skips(
    fake_persistence_uow, fake_persistence_redis
) -> None:
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    handler = WorkerPersistenceHandler(
        uow=fake_persistence_uow, redis_client=fake_persistence_redis
    )

    await handler.persist_success(
        assistant_message_id=None,
        user_id=uuid.uuid4(),
        content="content",
        tokens_input=100,
        tokens_output=50,
        search_context=None,
        start_time=0.0,
    )

    fake_persistence_uow.credit_repo.get_account_with_lock.assert_not_awaited()
    fake_persistence_uow.chat_repo.update_message_status.assert_not_awaited()


async def test_persist_success_passes_billing_model_name(
    fake_persistence_uow, fake_persistence_redis
) -> None:
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    handler = WorkerPersistenceHandler(
        uow=fake_persistence_uow, redis_client=fake_persistence_redis
    )

    with patch(
        "backend.application.chat.worker_persistence_handler.CreditService.spend_for_model_usage",
        new_callable=AsyncMock,
    ) as spend_for_model_usage:
        await handler.persist_success(
            assistant_message_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            content="content",
            tokens_input=100,
            tokens_output=50,
            search_context=None,
            start_time=0.0,
            model_name="billing-model",
        )

    assert spend_for_model_usage.await_args.kwargs["model_name"] == "billing-model"


async def test_persist_failure_redis_lock_cleanup_fails_still_writes_message(
    fake_persistence_uow, fake_persistence_redis
) -> None:
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    mock_redis_conn = AsyncMock()
    mock_redis_conn.delete = AsyncMock(side_effect=ConnectionError("Redis gone"))
    fake_persistence_redis.init = AsyncMock(return_value=mock_redis_conn)

    handler = WorkerPersistenceHandler(
        uow=fake_persistence_uow, redis_client=fake_persistence_redis
    )

    await handler.persist_failure(
        assistant_message_id=uuid.uuid4(),
        error_content="something failed",
        idempotency_lock_key="somekey",
    )

    mock_redis_conn.delete.assert_awaited_once_with("somekey")
    fake_persistence_uow.chat_repo.update_message_status.assert_awaited_once()
    assert (
        fake_persistence_uow.chat_repo.update_message_status.call_args.kwargs["status"]
        == MessageStatus.FAILED
    )


async def test_persist_failure_update_throws_swallowed(
    fake_persistence_uow, fake_persistence_redis
) -> None:
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    fake_persistence_uow.chat_repo.update_message_status = AsyncMock(
        side_effect=RuntimeError("DB error")
    )

    handler = WorkerPersistenceHandler(
        uow=fake_persistence_uow, redis_client=fake_persistence_redis
    )

    await handler.persist_failure(
        assistant_message_id=uuid.uuid4(),
        error_content="failed",
        idempotency_lock_key=None,
    )

    fake_persistence_uow.chat_repo.update_message_status.assert_awaited_once()
