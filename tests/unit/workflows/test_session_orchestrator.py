"""Session orchestrator kb_id override security tests.

职责：验证已有会话下 kb_id 覆盖被拒绝、新会话 kb_id 正常绑定的安全规则；
边界：使用 AsyncMock/MagicMock 替换 UoW 和 repos，不连接真实数据库；
副作用：无。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.application.chat.session_orchestrator import (
    ChatIdempotencyState,
    ChatSessionOrchestrator,
)
from backend.core.exceptions import AppException
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.models.schemas.chat.context_state import ContextState
from backend.services.feature_flag_service import (
    _AI_SYSTEM_FLAG_DEFAULTS,
    FeatureFlagService,
)
from backend.services.permission_service import PermissionService

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
    """prepare_request() 因 AppException 失败时，幂等锁必须被释放。"""

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
