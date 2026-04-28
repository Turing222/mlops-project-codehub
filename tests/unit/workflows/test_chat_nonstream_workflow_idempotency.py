import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ai.core import token_counter
from backend.models.schemas.chat_schema import LLMResultDTO
from backend.workflow.chat_nonstream_workflow import ChatNonStreamWorkflow

pytestmark = pytest.mark.asyncio


class _FakeEncoding:
    def encode(self, text: str):
        return list(text or "")


@pytest.fixture(autouse=True)
def clear_token_encoding_cache():
    token_counter._encoding_cache.clear()
    yield
    token_counter._encoding_cache.clear()


async def test_idempotency():
    uow = MagicMock()
    llm_service = AsyncMock()
    prompt_manager = MagicMock()

    mock_redis = AsyncMock()
    mock_redis.set.side_effect = [True, False]
    mock_redis.get.return_value = "PROCESSING"

    with (
        patch(
            "backend.workflow.chat_nonstream_workflow.redis_client.init",
            return_value=mock_redis,
        ),
        patch(
            "backend.workflow.chat_nonstream_workflow.MessageResponse.model_validate",
            return_value=MagicMock(),
        ),
        patch(
            "backend.workflow.chat_nonstream_workflow.ChatQueryResponse",
            return_value=MagicMock(),
        ),
        patch(
            "backend.ai.core.token_counter.tiktoken.get_encoding",
            return_value=_FakeEncoding(),
        ),
    ):
        workflow = ChatNonStreamWorkflow(uow, llm_service, prompt_manager)

        user_id = uuid.uuid4()
        client_req_id = "test-req-123"

        mock_user = MagicMock(used_tokens=0, max_tokens=1000)
        uow.user_repo = AsyncMock()
        uow.user_repo.get = AsyncMock(return_value=mock_user)
        uow.user_repo.get_with_lock = AsyncMock(return_value=mock_user)
        uow.__aenter__.return_value = uow

        try:
            await workflow.handle_query(user_id, "hello", client_request_id=client_req_id)
        except Exception:
            pass

        with pytest.raises(Exception, match="正在加速计算中"):
            await workflow.handle_query(user_id, "hello", client_request_id=client_req_id)


async def test_token_quota():
    uow = MagicMock()
    llm_service = AsyncMock()

    workflow = ChatNonStreamWorkflow(uow, llm_service)
    user_id = uuid.uuid4()

    mock_user = MagicMock(used_tokens=1000, max_tokens=1000)
    uow.user_repo = AsyncMock()
    uow.user_repo.get = AsyncMock(return_value=mock_user)
    uow.user_repo.get_with_lock = AsyncMock(return_value=mock_user)
    uow.__aenter__.return_value = uow

    with pytest.raises(Exception, match="Token 余额不足"):
        await workflow.handle_query(user_id, "hello")


async def test_token_recording():
    uow = MagicMock()
    llm_service = AsyncMock()

    llm_service.generate_response.return_value = LLMResultDTO(
        content="This is a test response",
        success=True,
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=100,
    )

    workflow = ChatNonStreamWorkflow(uow, llm_service)
    user_id = uuid.uuid4()

    mock_user = MagicMock(used_tokens=0, max_tokens=1000)
    uow.user_repo = AsyncMock()
    uow.user_repo.get = AsyncMock(return_value=mock_user)
    uow.__aenter__.return_value = uow

    session = MagicMock(id=uuid.uuid4(), title="Test Session")
    assistant_msg = MagicMock(id=uuid.uuid4())

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
            "backend.workflow.chat_nonstream_workflow.MessageResponse.model_validate",
            return_value=MagicMock(),
        ),
        patch(
            "backend.workflow.chat_nonstream_workflow.ChatQueryResponse",
            return_value=MagicMock(),
        ),
        patch(
            "backend.workflow.chat_nonstream_workflow.ChatMessageUpdater",
            MagicMock(),
        ) as mock_updater_cls,
        patch(
            "backend.ai.core.token_counter.tiktoken.get_encoding",
            return_value=_FakeEncoding(),
        ),
    ):
        mock_updater = mock_updater_cls.return_value
        mock_updater.update_as_success = AsyncMock(return_value=assistant_msg)
        uow.user_repo.get = AsyncMock(return_value=MagicMock(used_tokens=0, max_tokens=1000))
        uow.user_repo.get_with_lock = AsyncMock(return_value=MagicMock(used_tokens=0, max_tokens=1000))
        # 新接口：increment_used_tokens_guarded 返回 True（累加成功）
        uow.user_repo.increment_used_tokens = AsyncMock()
        uow.user_repo.increment_used_tokens_guarded = AsyncMock(return_value=True)
        # knowledge_repo 需要是 AsyncMock，否则 get_kb_by_name_for_user 无法 await
        uow.knowledge_repo = AsyncMock()
        uow.knowledge_repo.get_kb_by_name_for_user = AsyncMock(return_value=None)

        await workflow.handle_query(user_id, "hello")

        call_args = mock_updater.update_as_success.call_args[1]

        assert call_args.get("tokens_input") is not None
        assert call_args.get("tokens_output") == 5
        uow.user_repo.increment_used_tokens_guarded.assert_called_once()
