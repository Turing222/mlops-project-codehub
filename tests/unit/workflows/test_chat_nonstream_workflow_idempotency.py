"""Chat non-stream workflow idempotency and token quota tests.

职责：验证 ChatNonStreamWorkflow 的 Redis 幂等锁防重复、token 余额不足拒绝、
失败消息回放和 worker 派发成功；边界：不启动 HTTP stack、不连接真实 Redis；
副作用：无。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.application.chat.session_orchestrator import (
    ChatIdempotencyState,
    ChatSessionOrchestrator,
)
from backend.application.chat.web_nonstream_workflow import ChatNonStreamWorkflow
from backend.models.orm.chat import MessageStatus
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.models.schemas.chat.context_state import ContextState
from backend.models.schemas.chat.payloads import GenerationResult
from backend.services.feature_flag_service import (
    _AI_SYSTEM_FLAG_DEFAULTS,
    FeatureFlagService,
)

pytestmark = pytest.mark.asyncio


def _make_mock_feature_flag_service(
    overrides: dict[str, bool] | None = None,
) -> AsyncMock:
    flags = {
        **_AI_SYSTEM_FLAG_DEFAULTS,
        "enable-public-registration": True,
        "enable-closed-beta-login": False,
        **(overrides or {}),
    }
    svc = AsyncMock(spec=FeatureFlagService)
    svc.get_system_features = AsyncMock(return_value=flags)
    return svc


def _build_workflow(
    uow=None, dispatcher=None, redis_client=None
) -> ChatNonStreamWorkflow:
    return ChatNonStreamWorkflow(
        uow=uow or MagicMock(),
        dispatcher=dispatcher or AsyncMock(),
        redis_client=redis_client or AsyncMock(),
        permission_service=MagicMock(),
        feature_flag_service=_make_mock_feature_flag_service(),
    )


async def test_orchestrator_without_injected_session_manager_uses_default() -> None:
    uow = MagicMock()
    user_id = uuid.uuid4()
    session = MagicMock(id=uuid.uuid4(), title="Fallback Session", kb_id=None)
    now = datetime.now(UTC)
    assistant_msg = MagicMock(
        id=uuid.uuid4(),
        session_id=session.id,
        created_at=now,
        updated_at=now,
    )

    uow.user_repo = AsyncMock()
    uow.user_repo.get_with_lock = AsyncMock(
        return_value=MagicMock(used_tokens=0, max_tokens=1000)
    )
    uow.knowledge_repo = AsyncMock()
    uow.knowledge_repo.get_kb_by_name_for_user = AsyncMock(return_value=None)
    uow.chat_repo = AsyncMock()
    uow.chat_repo.get_context_state = AsyncMock(return_value=ContextState())
    uow.credit_repo = AsyncMock()
    credit_account = MagicMock()
    credit_account.balance = 10_000
    uow.credit_repo.get_account_with_lock = AsyncMock(return_value=credit_account)
    uow.credit_repo.get_transaction_by_idempotency_key = AsyncMock(return_value=None)
    uow.credit_repo.get_usage_record_by_chat_message_id = AsyncMock(return_value=None)
    uow.__aenter__.return_value = uow

    orchestrator = ChatSessionOrchestrator(
        uow,
        AsyncMock(),
        MagicMock(),
        _make_mock_feature_flag_service(),
    )

    with (
        patch(
            "backend.services.chat_service.SessionManager.ensure_session",
            AsyncMock(return_value=session),
        ) as ensure_session,
        patch(
            "backend.services.chat_service.SessionManager.create_user_message",
            AsyncMock(),
        ),
        patch(
            "backend.services.chat_service.SessionManager.create_assistant_message",
            AsyncMock(return_value=assistant_msg),
        ),
        patch(
            "backend.services.chat_service.SessionManager.get_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch(
            "backend.application.chat.session_orchestrator.history_to_conversation_messages",
            return_value=[],
        ),
    ):
        prepared = await orchestrator.prepare_request(
            command=ChatQueryCommand(user_id=user_id, query_text="hello"),
            idempotency=ChatIdempotencyState(
                lock_key=None,
                lock_token=None,
                is_new=True,
                value=None,
            ),
            trace_attrs={},
            span_prefix="chat.test",
        )

    assert prepared.session is session
    assert prepared.assistant_message is assistant_msg
    ensure_session.assert_awaited_once()


async def test_idempotency_lock_prevents_duplicate_request() -> None:
    uow = MagicMock()

    mock_redis = AsyncMock()
    mock_redis.set.side_effect = [True, False]
    mock_redis.get.return_value = "processing:test-uuid"

    workflow = _build_workflow(uow=uow, redis_client=mock_redis)

    user_id = uuid.uuid4()
    client_req_id = "test-req-123"

    mock_user = MagicMock(used_tokens=0, max_tokens=1000)
    uow.user_repo = AsyncMock()
    uow.user_repo.get = AsyncMock(return_value=mock_user)
    uow.user_repo.get_with_lock = AsyncMock(return_value=mock_user)
    uow.credit_repo = AsyncMock()
    credit_account = MagicMock()
    credit_account.balance = 10_000
    uow.credit_repo.get_account_with_lock = AsyncMock(return_value=credit_account)
    uow.credit_repo.get_transaction_by_idempotency_key = AsyncMock(return_value=None)
    uow.credit_repo.get_usage_record_by_chat_message_id = AsyncMock(return_value=None)
    uow.__aenter__.return_value = uow

    first_call_error: Exception | None = None
    try:
        await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
                client_request_id=client_req_id,
            )
        )
    except Exception as exc:
        first_call_error = exc

    assert "正在加速计算中" not in str(first_call_error)
    mock_redis.set.assert_awaited_once()
    lock_key, lock_token = mock_redis.set.await_args.args
    assert lock_key == f"idempotency:chat:{user_id}:{client_req_id}"
    assert lock_token.startswith("processing:")
    assert mock_redis.set.await_args.kwargs == {"nx": True, "ex": 300}

    with pytest.raises(Exception, match="正在加速计算中"):
        await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
                client_request_id=client_req_id,
            )
        )


async def test_token_quota_exceeded_raises_error() -> None:
    uow = MagicMock()
    workflow = _build_workflow(uow=uow)
    user_id = uuid.uuid4()

    mock_user = MagicMock(used_tokens=1000, max_tokens=1000)
    uow.user_repo = AsyncMock()
    uow.user_repo.get = AsyncMock(return_value=mock_user)
    uow.user_repo.get_with_lock = AsyncMock(return_value=mock_user)
    uow.knowledge_repo = AsyncMock()
    uow.knowledge_repo.get_kb_by_name_for_user = AsyncMock(return_value=None)
    uow.chat_repo = AsyncMock()
    uow.chat_repo.get_context_state = AsyncMock(return_value=ContextState())
    uow.credit_repo = AsyncMock()
    credit_account = MagicMock()
    credit_account.balance = 0
    uow.credit_repo.get_account_with_lock = AsyncMock(return_value=credit_account)
    uow.credit_repo.get_transaction_by_idempotency_key = AsyncMock(return_value=None)
    uow.credit_repo.get_usage_record_by_chat_message_id = AsyncMock(return_value=None)

    session = MagicMock(id=uuid.uuid4(), title="Session", kb_id=None)
    assistant_msg = MagicMock(
        id=uuid.uuid4(),
        session_id=session.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    with (
        patch(
            "backend.services.chat_service.SessionManager.ensure_session",
            AsyncMock(return_value=session),
        ),
        patch(
            "backend.services.chat_service.SessionManager.create_user_message",
            AsyncMock(),
        ),
        patch(
            "backend.services.chat_service.SessionManager.create_assistant_message",
            AsyncMock(return_value=assistant_msg),
        ),
        patch(
            "backend.services.chat_service.SessionManager.get_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch(
            "backend.application.chat.session_orchestrator.history_to_conversation_messages",
            return_value=[],
        ),
        pytest.raises(Exception, match="Credits 余额不足"),
    ):
        await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
            )
        )


async def test_idempotency_replay_with_non_success_message_does_not_prepare_request() -> (
    None
):
    uow = MagicMock()
    user_id = uuid.uuid4()
    client_req_id = "test-req-failed"
    mock_redis = AsyncMock()
    # Redis SET NX returns False when replaying a previously recorded request.
    mock_redis.set.return_value = False
    mock_redis.get.return_value = "completed:test-uuid"
    workflow = _build_workflow(uow=uow, redis_client=mock_redis)

    failed_msg = MagicMock(status=MessageStatus.FAILED)
    uow.chat_repo = AsyncMock()
    uow.chat_repo.get_message_by_client_request_id = AsyncMock(return_value=failed_msg)
    uow.__aenter__.return_value = uow

    with (
        patch(
            "backend.application.chat.session_orchestrator.ChatSessionOrchestrator.prepare_request",
            AsyncMock(),
        ) as prepare_request,
        pytest.raises(Exception, match="刷新页面"),
    ):
        await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
                client_request_id=client_req_id,
            )
        )

    prepare_request.assert_not_awaited()


async def test_idempotency_replay_with_success_message_returns_cached_answer() -> None:
    uow = MagicMock()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    client_req_id = "test-req-success"
    now = datetime.now(UTC)
    mock_redis = AsyncMock()
    # Redis SET NX returns False when replaying a previously recorded request.
    mock_redis.set.return_value = False
    mock_redis.get.return_value = str(uuid.uuid4())
    workflow = _build_workflow(uow=uow, redis_client=mock_redis)

    success_msg = MagicMock(
        id=uuid.uuid4(),
        session_id=session_id,
        role="assistant",
        content="cached answer",
        status=MessageStatus.SUCCESS,
        latency_ms=123,
        search_context={"hits": []},
        message_metadata={},
        created_at=now,
        updated_at=now,
    )
    session = MagicMock(id=session_id, title="Cached Session")
    uow.chat_repo = AsyncMock()
    uow.chat_repo.get_message_by_client_request_id = AsyncMock(return_value=success_msg)
    uow.chat_repo.get_session = AsyncMock(return_value=session)
    uow.read_context.return_value = uow
    uow.__aenter__.return_value = uow

    with patch(
        "backend.application.chat.session_orchestrator.ChatSessionOrchestrator.prepare_request",
        AsyncMock(),
    ) as prepare_request:
        result = await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
                client_request_id=client_req_id,
            )
        )

    assert result.session_id == session_id
    assert result.session_title == "Cached Session"
    assert result.answer.id == success_msg.id
    assert result.answer.content == "cached answer"
    uow.chat_repo.get_message_by_client_request_id.assert_awaited_once_with(
        client_req_id,
        user_id,
    )
    uow.chat_repo.get_session.assert_awaited_once_with(session_id)
    prepare_request.assert_not_awaited()


async def test_worker_dispatch_on_success() -> None:
    uow = MagicMock()
    user_id = uuid.uuid4()

    mock_worker_result = GenerationResult(
        success=True,
        content="Hello from worker",
        tokens_input=10,
        tokens_output=5,
        search_context=None,
        latency_ms=200,
    )
    mock_dispatcher = AsyncMock()
    mock_dispatcher.enqueue_nonstream = AsyncMock(return_value=mock_worker_result)
    workflow = _build_workflow(uow=uow, dispatcher=mock_dispatcher)

    mock_user = MagicMock(used_tokens=0, max_tokens=1000)
    uow.user_repo = AsyncMock()
    uow.user_repo.get_with_lock = AsyncMock(return_value=mock_user)
    uow.user_repo.try_increment_used_tokens_with_limit = AsyncMock(return_value=True)
    uow.knowledge_repo = AsyncMock()
    uow.knowledge_repo.get_kb_by_name_for_user = AsyncMock(return_value=None)
    uow.chat_repo = AsyncMock()
    uow.chat_repo.get_context_state = AsyncMock(return_value=ContextState())
    uow.credit_repo = AsyncMock()
    credit_account = MagicMock()
    credit_account.balance = 10_000
    uow.credit_repo.get_account_with_lock = AsyncMock(return_value=credit_account)
    uow.credit_repo.get_transaction_by_idempotency_key = AsyncMock(return_value=None)
    uow.credit_repo.get_usage_record_by_chat_message_id = AsyncMock(return_value=None)
    uow.__aenter__.return_value = uow

    session = MagicMock(id=uuid.uuid4(), title="Test Session", kb_id=None)
    now = datetime.now(UTC)
    assistant_msg = MagicMock(
        id=uuid.uuid4(),
        session_id=session.id,
        created_at=now,
        updated_at=now,
    )

    with (
        patch(
            "backend.services.chat_service.SessionManager.ensure_session",
            AsyncMock(return_value=session),
        ),
        patch(
            "backend.services.chat_service.SessionManager.create_user_message",
            AsyncMock(),
        ),
        patch(
            "backend.services.chat_service.SessionManager.create_assistant_message",
            AsyncMock(return_value=assistant_msg),
        ),
        patch(
            "backend.services.chat_service.SessionManager.get_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch(
            "backend.application.chat.session_orchestrator.history_to_conversation_messages",
            return_value=[],
        ),
    ):
        result = await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
            )
        )

    assert result is not None
    assert result.session_id == session.id
    assert result.session_title == "Test Session"
    assert result.answer.content == "Hello from worker"
    mock_dispatcher.enqueue_nonstream.assert_awaited_once()
