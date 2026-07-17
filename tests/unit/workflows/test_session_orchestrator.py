"""Session orchestrator kb_id override security tests.

职责：验证已有会话下 kb_id 覆盖被拒绝、新会话 kb_id 正常绑定的安全规则；
边界：使用 AsyncMock/MagicMock 替换 UoW 和 repos，不连接真实数据库；
副作用：无。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from backend.application.chat.session_orchestrator import (
    ChatIdempotencyState,
    ChatPreparedRequest,
    ChatSessionOrchestrator,
)
from backend.core.exceptions import AppException
from backend.models.enums import ChatGenerationStatus, MessageStatus
from backend.models.schemas.chat.commands import (
    ChatQueryCommand,
    RetryChatGenerationCommand,
)
from backend.models.schemas.chat.context_state import ContextState
from backend.models.schemas.chat.payloads import GENERATION_REQUEST_CONTEXT_KEY
from backend.services.feature_flag_service import (
    _AI_SYSTEM_FLAG_DEFAULTS,
    FeatureFlagService,
)
from backend.services.permission_service import PermissionService


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


def _make_idempotency() -> ChatIdempotencyState:
    return ChatIdempotencyState(
        lock_key=None,
        lock_token=None,
        is_new=True,
        value=None,
    )


def _build_orchestrator() -> tuple[ChatSessionOrchestrator, MagicMock]:
    """Build orchestrator with mocked UoW; return (orchestrator, uow)."""
    from contextlib import asynccontextmanager

    uow = MagicMock()
    uow.user_repo = AsyncMock()
    uow.knowledge_repo = AsyncMock()
    uow.chat_repo = AsyncMock()

    # Mock credit_repo
    uow.credit_repo = AsyncMock()
    credit_account = MagicMock()
    credit_account.balance = 10_000
    uow.credit_repo.get_account_with_lock = AsyncMock(return_value=credit_account)
    uow.credit_repo.create_account = AsyncMock(return_value=credit_account)
    uow.credit_repo.get_transaction_by_idempotency_key = AsyncMock(return_value=None)
    uow.credit_repo.get_usage_record_by_chat_message_id = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _noop_savepoint():
        yield uow

    uow.savepoint = _noop_savepoint
    uow.__aenter__.return_value = uow

    redis_client = AsyncMock()
    permission_service = MagicMock(spec=PermissionService)
    feature_flag_service = _make_mock_feature_flag_service()
    orchestrator = ChatSessionOrchestrator(
        uow,
        redis_client,
        permission_service,
        feature_flag_service,
    )
    return orchestrator, uow


async def test_queue_generation_request_commits_attempt_fence_before_dispatch() -> None:
    orchestrator, uow = _build_orchestrator()
    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    uow.chat_repo.try_queue_generation_request.return_value = True
    prepared = ChatPreparedRequest(
        session=MagicMock(),
        generation_request=MagicMock(id=request_id, attempt=3),
        assistant_message=MagicMock(),
        generation_payload=MagicMock(),
        lock_key="lock:test",
        lock_token="processing:test",
        trace_attrs={},
    )

    attempt = await orchestrator.queue_generation_request(
        prepared=prepared,
        user_id=user_id,
        task_id="task-3",
    )

    assert attempt.request_id == request_id
    assert attempt.attempt == 3
    assert attempt.task_id == "task-3"
    queue_kwargs = uow.chat_repo.try_queue_generation_request.await_args.kwargs
    assert queue_kwargs["user_id"] == user_id
    assert queue_kwargs["lease_token"] == attempt.lease_token
    assert queue_kwargs["recovery_due_at"] > queue_kwargs["queued_at"]


async def test_prepare_retry_request_rebuilds_context_and_advances_attempt() -> None:
    orchestrator, uow = _build_orchestrator()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    request_id = uuid.uuid4()
    generation_request = MagicMock(
        id=request_id,
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        status=ChatGenerationStatus.FAILED,
        attempt=1,
        retryable=True,
        reserved_credits=3,
    )
    user_message = MagicMock(
        id=user_message_id,
        role="user",
        content="retry this",
        message_metadata={
            GENERATION_REQUEST_CONTEXT_KEY: {
                "schema_version": 1,
                "enable_external_context": True,
                "context_mode": "web_only",
                "billing_model_name": "model-a",
                "extra_body": {"thinking": {"type": "enabled"}},
            }
        },
    )
    assistant_message = MagicMock(
        id=assistant_message_id,
        role="assistant",
        status=MessageStatus.FAILED,
    )
    session = MagicMock(id=session_id, kb_id=None, title="Retry")
    uow.chat_repo.get_generation_request_for_actor.return_value = generation_request
    uow.chat_repo.get_message.side_effect = [user_message, assistant_message]
    uow.chat_repo.get_session_messages.return_value = [
        user_message,
        assistant_message,
    ]
    uow.chat_repo.get_context_state.return_value = ContextState()
    uow.chat_repo.try_retry_generation_request.return_value = 2
    uow.chat_repo.reset_assistant_message_for_retry.return_value = True
    uow.user_repo.get_with_lock.return_value = MagicMock(
        used_tokens=0,
        max_tokens=100_000,
    )
    orchestrator._session_manager.ensure_session = AsyncMock(return_value=session)

    prepared = await orchestrator.prepare_retry_request(
        command=RetryChatGenerationCommand(
            user_id=user_id,
            generation_request_id=request_id,
            expected_attempt=1,
        ),
        trace_attrs={},
    )

    assert prepared.generation_request.attempt == 2
    assert prepared.assistant_message is assistant_message
    assert prepared.generation_payload.query_text == "retry this"
    assert prepared.generation_payload.enable_external_context is True
    assert prepared.generation_payload.context_mode == "web_only"
    assert prepared.generation_payload.billing_model_name == "model-a"
    assert prepared.generation_payload.conversation_history == [
        {"role": "user", "content": "retry this"}
    ]
    uow.chat_repo.try_retry_generation_request.assert_awaited_once()
    uow.chat_repo.reset_assistant_message_for_retry.assert_awaited_once_with(
        message_id=assistant_message_id
    )


@pytest.mark.parametrize(
    ("status", "attempt", "expected_attempt", "retryable", "expected_code"),
    [
        (
            ChatGenerationStatus.FAILED,
            2,
            1,
            True,
            "CHAT_RETRY_ATTEMPT_CONFLICT",
        ),
        (
            ChatGenerationStatus.RUNNING,
            2,
            2,
            False,
            "CHAT_REQUEST_STILL_RUNNING",
        ),
        (
            ChatGenerationStatus.SUCCEEDED,
            2,
            2,
            False,
            "CHAT_REQUEST_ALREADY_SUCCEEDED",
        ),
        (
            ChatGenerationStatus.FAILED,
            2,
            2,
            False,
            "CHAT_REQUEST_NOT_RETRYABLE",
        ),
    ],
)
async def test_prepare_retry_request_rejects_invalid_state_with_stable_code(
    status: ChatGenerationStatus,
    attempt: int,
    expected_attempt: int,
    retryable: bool,
    expected_code: str,
) -> None:
    orchestrator, uow = _build_orchestrator()
    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    uow.chat_repo.get_generation_request_for_actor.return_value = MagicMock(
        id=request_id,
        status=status,
        attempt=attempt,
        retryable=retryable,
    )

    with pytest.raises(AppException) as exc_info:
        await orchestrator.prepare_retry_request(
            command=RetryChatGenerationCommand(
                user_id=user_id,
                generation_request_id=request_id,
                expected_attempt=expected_attempt,
            ),
            trace_attrs={},
        )

    assert exc_info.value.code == expected_code
    assert exc_info.value.status_code == 409
    uow.chat_repo.try_retry_generation_request.assert_not_awaited()


class TestKbIdMismatchRejection:
    """已有会话下 kb_id 覆盖安全规则测试。"""

    async def test_existing_session_same_kb_id_allowed(self) -> None:
        """command.kb_id == session.kb_id → 允许，payload.kb_id 使用 session.kb_id。"""
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        kb_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        session = MagicMock(
            id=session_id, user_id=user_id, kb_id=kb_id, workspace_id=None
        )
        uow.chat_repo.get_session.return_value = session

        kb = MagicMock(workspace_id=None, user_id=user_id)
        uow.knowledge_repo.get_kb.return_value = kb

        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        assistant_msg = MagicMock(id=uuid.uuid4())
        uow.chat_repo.get_context_state.return_value = ContextState()

        with (
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
                command=ChatQueryCommand(
                    user_id=user_id,
                    query_text="test",
                    session_id=session_id,
                    kb_id=kb_id,
                ),
                idempotency=_make_idempotency(),
                trace_attrs={},
                span_prefix="test",
            )

        assert prepared.generation_payload.kb_id == kb_id

    async def test_existing_session_different_kb_id_rejected(self) -> None:
        """command.kb_id != session.kb_id → 拒绝，抛 KB_ID_MISMATCH (400)。"""
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session_kb_id = uuid.uuid4()
        different_kb_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        session = MagicMock(
            id=session_id,
            user_id=user_id,
            kb_id=session_kb_id,
            workspace_id=None,
        )
        uow.chat_repo.get_session.return_value = session

        kb = MagicMock(workspace_id=None, user_id=user_id)
        uow.knowledge_repo.get_kb.return_value = kb

        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        with (
            patch(
                "backend.services.chat_service.SessionManager.create_user_message",
                AsyncMock(),
            ),
            patch(
                "backend.services.chat_service.SessionManager.create_assistant_message",
                AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(
                "backend.services.chat_service.SessionManager.get_session_messages",
                AsyncMock(return_value=[]),
            ),
            patch(
                "backend.application.chat.session_orchestrator.history_to_conversation_messages",
                return_value=[],
            ),
            pytest.raises(AppException) as exc_info,
        ):
            await orchestrator.prepare_request(
                command=ChatQueryCommand(
                    user_id=user_id,
                    query_text="test",
                    session_id=session_id,
                    kb_id=different_kb_id,
                ),
                idempotency=_make_idempotency(),
                trace_attrs={},
                span_prefix="test",
            )

        assert exc_info.value.code == "KB_ID_MISMATCH"
        assert exc_info.value.status_code == 400

    async def test_existing_session_no_kb_id_uses_session_kb(self) -> None:
        """command.kb_id is None → 使用 session.kb_id，不拒绝。"""
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session_kb_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        session = MagicMock(
            id=session_id,
            user_id=user_id,
            kb_id=session_kb_id,
            workspace_id=None,
        )
        uow.chat_repo.get_session.return_value = session

        kb = MagicMock(workspace_id=None, user_id=user_id)
        uow.knowledge_repo.get_kb.return_value = kb

        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        assistant_msg = MagicMock(id=uuid.uuid4())
        uow.chat_repo.get_context_state.return_value = ContextState()

        with (
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
                command=ChatQueryCommand(
                    user_id=user_id,
                    query_text="test",
                    session_id=session_id,
                    kb_id=None,
                ),
                idempotency=_make_idempotency(),
                trace_attrs={},
                span_prefix="test",
            )

        assert prepared.generation_payload.kb_id == session_kb_id

    async def test_new_session_kb_id_allowed(self) -> None:
        """新会话 + kb_id → 经过权限校验后正常绑定。"""
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        kb = MagicMock(id=kb_id, workspace_id=None, user_id=user_id)
        uow.knowledge_repo.get_kb.return_value = kb

        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        new_session = MagicMock(id=uuid.uuid4(), kb_id=kb_id, workspace_id=None)
        uow.chat_repo.create_session.return_value = new_session

        assistant_msg = MagicMock(id=uuid.uuid4())
        uow.chat_repo.get_context_state.return_value = ContextState()

        with (
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
                command=ChatQueryCommand(
                    user_id=user_id,
                    query_text="test",
                    session_id=None,
                    kb_id=kb_id,
                ),
                idempotency=_make_idempotency(),
                trace_attrs={},
                span_prefix="test",
            )

        assert prepared.generation_payload.kb_id == kb_id

    async def test_new_session_no_kb_id_does_not_trigger_rag(self) -> None:
        """新会话 + 无 kb_id → 不触发 RAG (kb_id 为 None)。"""
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        new_session = MagicMock(id=uuid.uuid4(), kb_id=None, workspace_id=None)
        uow.chat_repo.create_session.return_value = new_session

        assistant_msg = MagicMock(id=uuid.uuid4())
        uow.chat_repo.get_context_state.return_value = ContextState()

        with (
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
                command=ChatQueryCommand(
                    user_id=user_id,
                    query_text="test",
                    session_id=None,
                    kb_id=None,
                ),
                idempotency=_make_idempotency(),
                trace_attrs={},
                span_prefix="test",
            )

        assert prepared.generation_payload.kb_id is None


class TestIdempotencyLockReleaseOnPrepareFailure:
    """prepare_request() 失败时，幂等锁必须被释放。"""

    async def test_integrity_error_releases_lock_and_returns_stable_conflict(
        self,
    ) -> None:
        """A durable identity race must release Redis and hide SQL details."""
        orchestrator, _ = _build_orchestrator()
        idempotency = ChatIdempotencyState(
            lock_key="idempotency:chat:user-1:request-1",
            lock_token="processing:abc",
            is_new=True,
            value=None,
        )
        conflict = IntegrityError(
            "INSERT INTO chat_messages (client_request_id) VALUES (:request_id)",
            {"request_id": "request-1"},
            RuntimeError("duplicate client_request_id"),
        )

        with (
            patch.object(
                orchestrator,
                "_prepare_request_inner",
                AsyncMock(side_effect=conflict),
            ),
            patch.object(
                orchestrator,
                "release_idempotency",
                AsyncMock(),
            ) as release_idempotency,
            pytest.raises(AppException) as exc_info,
        ):
            await orchestrator.prepare_request(
                command=ChatQueryCommand(
                    user_id=uuid.uuid4(),
                    query_text="retry",
                    client_request_id="request-1",
                ),
                idempotency=idempotency,
                trace_attrs={},
                span_prefix="test",
            )

        assert exc_info.value.code == "CHAT_REQUEST_ALREADY_EXISTS"
        release_idempotency.assert_awaited_once_with(idempotency)

    async def test_unexpected_error_releases_lock_and_is_reraised(self) -> None:
        """Unexpected prepare failures must not strand the Redis lock."""
        orchestrator, _ = _build_orchestrator()
        idempotency = ChatIdempotencyState(
            lock_key="idempotency:chat:user-1:request-1",
            lock_token="processing:abc",
            is_new=True,
            value=None,
        )
        failure = RuntimeError("database unavailable")

        with (
            patch.object(
                orchestrator,
                "_prepare_request_inner",
                AsyncMock(side_effect=failure),
            ),
            patch.object(
                orchestrator,
                "release_idempotency",
                AsyncMock(),
            ) as release_idempotency,
            pytest.raises(RuntimeError, match="database unavailable"),
        ):
            await orchestrator.prepare_request(
                command=ChatQueryCommand(
                    user_id=uuid.uuid4(),
                    query_text="retry",
                    client_request_id="request-1",
                ),
                idempotency=idempotency,
                trace_attrs={},
                span_prefix="test",
            )

        release_idempotency.assert_awaited_once_with(idempotency)

    async def test_kb_id_mismatch_releases_idempotency_lock(self) -> None:
        """KB_ID_MISMATCH 导致 prepare_request 失败 → release_idempotency 被调用。"""
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session_kb_id = uuid.uuid4()
        different_kb_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        session = MagicMock(
            id=session_id,
            user_id=user_id,
            kb_id=session_kb_id,
            workspace_id=None,
        )
        uow.chat_repo.get_session.return_value = session

        kb = MagicMock(workspace_id=None, user_id=user_id)
        uow.knowledge_repo.get_kb.return_value = kb

        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        with patch.object(
            orchestrator, "release_idempotency", AsyncMock()
        ) as mock_release:
            with pytest.raises(AppException) as exc_info:
                await orchestrator.prepare_request(
                    command=ChatQueryCommand(
                        user_id=user_id,
                        query_text="test",
                        session_id=session_id,
                        kb_id=different_kb_id,
                    ),
                    idempotency=ChatIdempotencyState(
                        lock_key="idempotency:chat:test",
                        lock_token="processing:abc",
                        is_new=True,
                        value=None,
                    ),
                    trace_attrs={},
                    span_prefix="test",
                )

            assert exc_info.value.code == "KB_ID_MISMATCH"
            mock_release.assert_awaited_once()

    async def test_kb_forbidden_releases_idempotency_lock(self) -> None:
        """KNOWLEDGE_BASE_FORBIDDEN 导致 prepare_request 失败 → release_idempotency 被调用。"""
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        session = MagicMock(
            id=session_id,
            user_id=user_id,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )
        uow.chat_repo.get_session.return_value = session

        kb = MagicMock(workspace_id=workspace_id, user_id=user_id)
        uow.knowledge_repo.get_kb.return_value = kb

        # 用户被移出 workspace
        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=False)
        )

        with patch.object(
            orchestrator, "release_idempotency", AsyncMock()
        ) as mock_release:
            with pytest.raises(AppException) as exc_info:
                await orchestrator.prepare_request(
                    command=ChatQueryCommand(
                        user_id=user_id,
                        query_text="test",
                        session_id=session_id,
                        kb_id=None,
                    ),
                    idempotency=ChatIdempotencyState(
                        lock_key="idempotency:chat:test",
                        lock_token="processing:abc",
                        is_new=True,
                        value=None,
                    ),
                    trace_attrs={},
                    span_prefix="test",
                )

            assert exc_info.value.code == "KNOWLEDGE_BASE_FORBIDDEN"
            mock_release.assert_awaited_once()

    async def test_no_lock_skips_release_on_failure(self) -> None:
        """无 client_request_id → 无锁 → release_idempotency 不被调用（但也不报错）。"""
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session_kb_id = uuid.uuid4()
        different_kb_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        session = MagicMock(
            id=session_id,
            user_id=user_id,
            kb_id=session_kb_id,
            workspace_id=None,
        )
        uow.chat_repo.get_session.return_value = session

        kb = MagicMock(workspace_id=None, user_id=user_id)
        uow.knowledge_repo.get_kb.return_value = kb

        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        # lock_key=None, lock_token=None → 无锁
        no_lock_idempotency = ChatIdempotencyState(
            lock_key=None,
            lock_token=None,
            is_new=True,
            value=None,
        )

        with patch.object(
            orchestrator, "release_idempotency", AsyncMock()
        ) as mock_release:
            with pytest.raises(AppException) as exc_info:
                await orchestrator.prepare_request(
                    command=ChatQueryCommand(
                        user_id=user_id,
                        query_text="test",
                        session_id=session_id,
                        kb_id=different_kb_id,
                    ),
                    idempotency=no_lock_idempotency,
                    trace_attrs={},
                    span_prefix="test",
                )

            assert exc_info.value.code == "KB_ID_MISMATCH"
            # release_idempotency 仍然被调用，但内部会因为 lock_key=None 提前返回
            mock_release.assert_awaited_once_with(no_lock_idempotency)


class TestCreditPrecheckLockOrder:
    """Credit pre-check must run BEFORE session/message creation to avoid deadlock."""

    async def test_credit_precheck_runs_before_session_creation(self) -> None:
        """get_with_lock (credit pre-check) must be called before ensure_session."""
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()

        call_order: list[str] = []

        async def tracked_get_with_lock(uid: object) -> object:
            call_order.append("get_with_lock")
            return MagicMock(max_tokens=100000, used_tokens=0)

        uow.user_repo.get_with_lock = tracked_get_with_lock

        session_obj = MagicMock(id=uuid.uuid4(), kb_id=None, workspace_id=None)

        async def tracked_ensure_session(*args: object, **kwargs: object) -> object:
            call_order.append("ensure_session")
            return session_obj

        with (
            patch(
                "backend.services.chat_service.SessionManager.ensure_session",
                new=tracked_ensure_session,
            ),
            patch(
                "backend.services.chat_service.SessionManager.create_user_message",
                new=AsyncMock(),
            ),
            patch(
                "backend.services.chat_service.SessionManager.create_assistant_message",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(
                "backend.services.chat_service.SessionManager.get_session_messages",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "backend.application.chat.session_orchestrator.history_to_conversation_messages",
                return_value=[],
            ),
        ):
            uow.chat_repo.get_context_state.return_value = ContextState()

            await orchestrator.prepare_request(
                command=ChatQueryCommand(
                    user_id=user_id,
                    query_text="test",
                    session_id=None,
                    kb_id=None,
                ),
                idempotency=_make_idempotency(),
                trace_attrs={},
                span_prefix="test",
            )

        assert call_order[0] == "get_with_lock"
        assert call_order[1] == "ensure_session"


class TestEnableExternalContextPassthrough:
    """enable_external_context must pass from ChatQueryCommand to GenerationPayload."""

    async def test_prepare_request_passes_enable_external_context_to_payload(
        self,
    ) -> None:
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        new_session = MagicMock(id=uuid.uuid4(), kb_id=None, workspace_id=None)
        uow.chat_repo.create_session.return_value = new_session

        assistant_msg = MagicMock(id=uuid.uuid4())
        uow.chat_repo.get_context_state.return_value = ContextState()

        with (
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
                command=ChatQueryCommand(
                    user_id=user_id,
                    query_text="test",
                    session_id=None,
                    kb_id=None,
                    enable_external_context=True,
                    context_mode="auto",
                ),
                idempotency=_make_idempotency(),
                trace_attrs={},
                span_prefix="test",
            )

        assert prepared.generation_payload.enable_external_context is True
        assert prepared.generation_payload.context_mode == "auto"

    async def test_prepare_request_passes_billing_model_name_to_payload(self) -> None:
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )
        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        new_session = MagicMock(id=uuid.uuid4(), kb_id=None, workspace_id=None)
        uow.chat_repo.create_session.return_value = new_session
        assistant_msg = MagicMock(id=uuid.uuid4())
        uow.chat_repo.get_context_state.return_value = ContextState()

        with (
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
            patch(
                "backend.application.chat.session_orchestrator._resolve_billing_model_name",
                return_value="billing-model",
            ),
        ):
            prepared = await orchestrator.prepare_request(
                command=ChatQueryCommand(
                    user_id=user_id,
                    query_text="test",
                    session_id=None,
                    kb_id=None,
                ),
                idempotency=_make_idempotency(),
                trace_attrs={},
                span_prefix="test",
            )

        assert prepared.generation_payload.billing_model_name == "billing-model"

    async def test_prepare_request_enable_external_context_default_false(self) -> None:
        orchestrator, uow = _build_orchestrator()
        user_id = uuid.uuid4()

        uow.user_repo.get_with_lock.return_value = MagicMock(
            used_tokens=0, max_tokens=1000
        )

        orchestrator._session_manager.permission_service.has_permission_for_user_id = (
            AsyncMock(return_value=True)
        )

        new_session = MagicMock(id=uuid.uuid4(), kb_id=None, workspace_id=None)
        uow.chat_repo.create_session.return_value = new_session

        assistant_msg = MagicMock(id=uuid.uuid4())
        uow.chat_repo.get_context_state.return_value = ContextState()

        with (
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
                command=ChatQueryCommand(
                    user_id=user_id,
                    query_text="test",
                    session_id=None,
                    kb_id=None,
                ),
                idempotency=_make_idempotency(),
                trace_attrs={},
                span_prefix="test",
            )

        assert prepared.generation_payload.enable_external_context is False
        assert prepared.generation_payload.context_mode is None
