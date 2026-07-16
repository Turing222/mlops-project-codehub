"""Chat API component tests.

职责：验证 chat 路由的 ASGI 装配与请求/响应序列化；边界：用 dependency override 与 ASGITransport，不连真实下游；副作用：无。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.v1.endpoint import chat_api
from backend.application.chat.web_nonstream_workflow import ChatNonStreamWorkflow
from backend.config.settings import settings
from backend.models.enums import ChatGenerationStatus, MessageStatus
from backend.models.schemas.chat.context_state import ContextState
from backend.models.schemas.chat.dto import LLMQueryDTO, LLMResultDTO
from backend.models.schemas.chat.payloads import GenerationResult
from backend.services.feature_flag_service import (
    _AI_SYSTEM_FLAG_DEFAULTS,
    FeatureFlagService,
)

pytestmark = pytest.mark.component


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


def make_user(**overrides):
    now = datetime.now(UTC)
    data = {
        "id": uuid.uuid4(),
        "username": "chat_tester",
        "email": "chat_tester@example.com",
        "is_active": True,
        "is_superuser": False,
        "max_tokens": 10_000,
        "used_tokens": 0,
        "hashed_password": "not-used-in-tests",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_session(**overrides):
    now = datetime.now(UTC)
    data = {
        "id": uuid.uuid4(),
        "title": "已有会话",
        "user_id": uuid.uuid4(),
        "workspace_id": None,
        "kb_id": None,
        "llm_config": {},
        "total_tokens": 0,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_message(**overrides):
    now = datetime.now(UTC)
    data = {
        "id": uuid.uuid4(),
        "session_id": uuid.uuid4(),
        "role": "assistant",
        "content": "",
        "status": MessageStatus.THINKING,
        "search_context": None,
        "client_request_id": None,
        "tokens_input": 0,
        "tokens_output": 0,
        "latency_ms": None,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class FakeUserRepo:
    def __init__(self, user):
        self.user = user
        self.increment_calls: list[int] = []

    async def get(self, user_id: uuid.UUID):
        if user_id == self.user.id:
            return self.user
        return None

    async def get_with_lock(self, user_id: uuid.UUID):
        """SELECT FOR UPDATE 模拟：返回同一用户对象。"""
        return await self.get(user_id)

    async def increment_used_tokens(self, user_id: uuid.UUID, amount: int):
        assert user_id == self.user.id
        self.user.used_tokens += amount
        self.increment_calls.append(amount)

    async def try_increment_used_tokens_with_limit(
        self, user_id: uuid.UUID, amount: int
    ) -> bool:
        """条件原子累加模拟：检查上限并返回 bool。"""
        if self.user is None or user_id != self.user.id:
            return False
        if self.user.used_tokens + amount > self.user.max_tokens:
            return False
        self.user.used_tokens += amount
        self.increment_calls.append(amount)
        return True


class FakeChatRepo:
    def __init__(self):
        self.sessions: dict[uuid.UUID, SimpleNamespace] = {}
        self.messages: dict[uuid.UUID, SimpleNamespace] = {}
        self.session_messages: dict[uuid.UUID, list[SimpleNamespace]] = {}
        self.generation_requests: dict[uuid.UUID, SimpleNamespace] = {}

    def seed_session(self, session):
        self.sessions[session.id] = session
        self.session_messages.setdefault(session.id, [])
        return session

    def seed_message(self, message):
        self.messages[message.id] = message
        self.session_messages.setdefault(message.session_id, []).append(message)
        return message

    async def create_session(
        self,
        user_id: uuid.UUID,
        title: str,
        kb_id: uuid.UUID | None = None,
    ):
        session = make_session(user_id=user_id, title=title, kb_id=kb_id)
        return self.seed_session(session)

    async def get_session(self, session_id: uuid.UUID):
        return self.sessions.get(session_id)

    async def get_context_state(self, session_id: uuid.UUID) -> ContextState:
        return ContextState()

    async def create_generation_request(
        self,
        *,
        user_id: uuid.UUID,
        client_request_id: str,
        session_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
        user_message_id: uuid.UUID | None = None,
        assistant_message_id: uuid.UUID | None = None,
        recovery_due_at=None,
        reserved_credits: int = 0,
    ) -> SimpleNamespace:
        request = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=user_id,
            client_request_id=client_request_id,
            session_id=session_id,
            workspace_id=workspace_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            status=ChatGenerationStatus.PREPARED,
            attempt=1,
            recovery_due_at=recovery_due_at,
            reserved_credits=reserved_credits,
        )
        self.generation_requests[request.id] = request
        return request

    async def get_generation_request_by_client_request_id_for_actor(
        self,
        *,
        user_id: uuid.UUID,
        client_request_id: str,
    ) -> SimpleNamespace | None:
        return next(
            (
                request
                for request in self.generation_requests.values()
                if request.user_id == user_id
                and request.client_request_id == client_request_id
            ),
            None,
        )

    async def try_queue_generation_request(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        expected_attempt: int,
        task_id: str,
        lease_token: str,
        queued_at,
        recovery_due_at,
    ) -> bool:
        request = self.generation_requests.get(request_id)
        if (
            request is None
            or request.user_id != user_id
            or request.status != ChatGenerationStatus.PREPARED
            or request.attempt != expected_attempt
        ):
            return False
        request.status = ChatGenerationStatus.QUEUED
        request.task_id = task_id
        request.lease_token = lease_token
        request.queued_at = queued_at
        request.recovery_due_at = recovery_due_at
        return True

    async def create_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str,
        status: MessageStatus,
        client_request_id: str | None = None,
        search_context: dict | None = None,
        user_id: uuid.UUID | None = None,
        message_metadata: dict | None = None,
    ):
        message = make_message(
            session_id=session_id,
            role=role,
            content=content,
            status=status,
            client_request_id=client_request_id,
            search_context=search_context,
        )
        return self.seed_message(message)

    async def get_session_messages(
        self,
        session_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ):
        messages = list(self.session_messages.get(session_id, []))
        return messages[skip : skip + limit]

    async def update_message_status(
        self,
        message_id: uuid.UUID,
        status: MessageStatus,
        content: str | None = None,
        latency_ms: int | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        search_context: dict | None = None,
    ):
        message = self.messages.get(message_id)
        if message is None:
            return None

        message.status = status
        if content is not None:
            message.content = content
        if latency_ms is not None:
            message.latency_ms = latency_ms
        if tokens_input is not None:
            message.tokens_input = tokens_input
        if tokens_output is not None:
            message.tokens_output = tokens_output
        message.search_context = search_context
        message.updated_at = datetime.now(UTC)
        return message


class FakeKnowledgeRepo:
    """知识库仓储模拟，防止 Workflow 内 getattr 失败。"""

    async def get_kb_by_name_for_user(self, *, name: str, user_id: uuid.UUID):
        return None

    async def get_kb(self, kb_id: uuid.UUID):
        return None


class FakeCreditRepo:
    """积分仓储模拟，防止 Workflow 内 CreditService 访问失败。"""

    def __init__(self, balance: int = 10_000):
        self._balance = balance

    async def get_account(self, user_id: uuid.UUID):
        from backend.models.orm.credits import CreditAccount

        return CreditAccount(user_id=user_id, balance=self._balance)

    async def get_account_with_lock(self, user_id: uuid.UUID):
        from backend.models.orm.credits import CreditAccount

        return CreditAccount(user_id=user_id, balance=self._balance)

    async def get_account_by_id_with_lock(self, account_id: uuid.UUID):
        return None

    async def create_account(self, user_id: uuid.UUID):
        from backend.models.orm.credits import CreditAccount

        return CreditAccount(user_id=user_id, balance=100)

    async def update_account_balance(self, account_id: uuid.UUID, balance: int):
        pass

    async def try_decrement_balance(self, account_id: uuid.UUID, cost: int) -> bool:
        return True

    async def add_transaction(self, **kwargs):
        from backend.models.orm.credits import CreditTransaction

        return CreditTransaction(
            account_id=kwargs["account_id"],
            amount=kwargs["amount"],
            source=kwargs["source"],
        )

    async def get_transaction_by_idempotency_key(self, idempotency_key: str):
        return None

    async def create_usage_record(self, **kwargs):
        from backend.models.orm.credits import UsageRecord

        return UsageRecord(user_id=kwargs["user_id"], credit_cost=0)

    async def get_usage_record_by_chat_message_id(self, chat_message_id: uuid.UUID):
        return None

    async def list_transactions(self, **kwargs):
        return []

    async def count_transactions(
        self, account_id: uuid.UUID, source: str | None = None
    ) -> int:
        return 0

    async def get_expired_grants_sum(self, account_id: uuid.UUID, now=None) -> int:
        return 0

    async def get_already_expired_sum(self, account_id: uuid.UUID) -> int:
        return 0

    async def get_spent_sum(self, account_id: uuid.UUID) -> int:
        return 0

    async def list_accounts_needing_expiration(self, now=None):
        return []


class FakeUnitOfWork:
    def __init__(self, user_repo: FakeUserRepo, chat_repo: FakeChatRepo):
        self.user_repo = user_repo
        self.chat_repo = chat_repo
        self.knowledge_repo = FakeKnowledgeRepo()
        self.credit_repo = FakeCreditRepo()
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()
        return False

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    def savepoint(self):
        return self


class RecordingLLMService:
    def __init__(self):
        self.calls: list[LLMQueryDTO] = []

    async def generate_response(self, query: LLMQueryDTO) -> LLMResultDTO:
        self.calls.append(query)
        return LLMResultDTO(
            content="这是集成测试里的回答",
            success=True,
            prompt_tokens=18,
            completion_tokens=7,
            latency_ms=12,
        )

    async def stream_response(self, query: LLMQueryDTO):
        if False:
            yield query.query_text


@pytest.fixture(autouse=True)
def stable_test_environment():
    with patch(
        "backend.application.chat.web_nonstream_workflow.set_langfuse_trace_metadata",
    ):
        yield


@pytest.fixture
def api_context():
    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api/v1/chat")

    current_user = make_user()
    user_repo = FakeUserRepo(current_user)
    chat_repo = FakeChatRepo()
    uow = FakeUnitOfWork(user_repo=user_repo, chat_repo=chat_repo)
    llm_service = RecordingLLMService()
    mock_dispatcher = AsyncMock()
    mock_dispatcher.enqueue_nonstream = AsyncMock(
        return_value=GenerationResult(
            success=True,
            content="这是集成测试里的回答",
            tokens_input=10,
            tokens_output=5,
            search_context=None,
            latency_ms=200,
        )
    )
    workflow = ChatNonStreamWorkflow(
        uow=uow,
        dispatcher=mock_dispatcher,
        redis_client=AsyncMock(),
        permission_service=SimpleNamespace(
            has_permission_for_user_id=AsyncMock(return_value=True),
        ),
        feature_flag_service=_make_mock_feature_flag_service(),
    )

    # 依赖覆盖
    # 1. 核心业务依赖
    app.dependency_overrides[chat_api.get_current_active_user] = lambda: current_user
    app.dependency_overrides[chat_api.get_chat_nonstream_workflow] = lambda: workflow
    app.dependency_overrides[chat_api.chat_limiter] = lambda: None

    # 2. 修复存量 bug：测试用裸 FastAPI() 没走 lifespan，
    #    get_uow / get_audit_service / get_permission_service 都依赖
    #    request.app.state.session_factory（由 lifespan 注入），
    #    这里用 Fake 对象覆盖，断开对 app.state 的依赖。
    from backend.api.deps.audit import get_audit_service
    from backend.api.deps.permissions import get_permission_service
    from backend.api.deps.uow import get_uow
    from backend.services.audit_service import AuditRequestContext, AuditService
    from backend.services.permission_service import PermissionService

    app.dependency_overrides[get_uow] = lambda: uow
    app.dependency_overrides[get_audit_service] = lambda: AuditService(
        uow=uow,  # type: ignore[arg-type]
        request_context=AuditRequestContext(),
    )
    app.dependency_overrides[get_permission_service] = lambda: PermissionService(
        uow=uow
    )  # type: ignore[arg-type]

    ctx = SimpleNamespace(
        app=app,
        current_user=current_user,
        user_repo=user_repo,
        chat_repo=chat_repo,
        uow=uow,
        llm_service=llm_service,
        workflow=workflow,
    )
    yield ctx
    app.dependency_overrides.clear()


@pytest.fixture
async def client(api_context):
    transport = ASGITransport(app=api_context.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_query_sent_uses_memory_summary_and_updates_tokens(
    client,
    api_context,
    monkeypatch,
):
    monkeypatch.setattr(settings, "CHAT_MEMORY_RECENT_ROUNDS", 1)
    monkeypatch.setattr(settings, "CHAT_MEMORY_SNIPPET_CHARS", 60)
    monkeypatch.setattr(settings, "CHAT_MEMORY_SUMMARY_MAX_CHARS", 400)

    session = api_context.chat_repo.seed_session(
        make_session(user_id=api_context.current_user.id, title="历史会话")
    )
    api_context.chat_repo.seed_message(
        make_message(
            session_id=session.id,
            role="user",
            content="第一轮问题",
            status=MessageStatus.SUCCESS,
        )
    )
    api_context.chat_repo.seed_message(
        make_message(
            session_id=session.id,
            role="assistant",
            content="第一轮回答",
            status=MessageStatus.SUCCESS,
        )
    )
    api_context.chat_repo.seed_message(
        make_message(
            session_id=session.id,
            role="user",
            content="第二轮问题",
            status=MessageStatus.SUCCESS,
        )
    )
    api_context.chat_repo.seed_message(
        make_message(
            session_id=session.id,
            role="assistant",
            content="第二轮回答",
            status=MessageStatus.SUCCESS,
        )
    )

    response = await client.post(
        "/api/v1/chat/query_sent",
        json={
            "query": "第三轮问题",
            "session_id": str(session.id),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == str(session.id)
    assert body["session_title"] == "历史会话"
    assert body["answer"]["role"] == "assistant"
    assert body["answer"]["status"] == "success"
    assert body["answer"]["content"] == "这是集成测试里的回答"

    # Web workflow dispatches to worker via AbstractTaskDispatcher;
    # LLM invocation and final persistence are owned by the worker.
    mock_dispatcher = api_context.workflow.dispatcher
    mock_dispatcher.enqueue_nonstream.assert_awaited_once()
    dispatch_args = mock_dispatcher.enqueue_nonstream.call_args
    generation_payload = dispatch_args.kwargs["generation_payload"]
    assert dispatch_args.kwargs["generation_attempt"].task_id
    assert generation_payload["query_text"] == "第三轮问题"
    assert generation_payload["session_id"] == str(session.id)

    # Conversation history is still assembled on the web side and sent to worker.
    history = generation_payload["conversation_history"]
    assert history[-1] == {"role": "user", "content": "第三轮问题"}
    assert sum(msg["content"] == "第三轮问题" for msg in history) == 1
    assert {"role": "user", "content": "第二轮问题"} in history
    assert {"role": "assistant", "content": "第二轮回答"} in history


async def test_query_sent_rejects_blank_query(client):
    response = await client.post(
        "/api/v1/chat/query_sent",
        json={"query": "   "},
    )

    assert response.status_code == 422
