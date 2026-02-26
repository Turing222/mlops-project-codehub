import asyncio
import uuid
import sys
import os
from unittest.mock import AsyncMock, patch, MagicMock

# 设置 PYTHONPATH
sys.path.append(os.getcwd())

from backend.workflow.chat_workflow import ChatWorkflow
from backend.models.schemas.chat_schema import LLMResultDTO, MessageResponse, ChatQueryResponse
from backend.models.orm.chat import MessageStatus

async def test_idempotency():
    print("\nTesting Idempotency...")
    uow = MagicMock()
    llm_service = AsyncMock()
    prompt_manager = MagicMock()
    
    # Mock Redis
    mock_redis = AsyncMock()
    mock_redis.set.side_effect = [True, False]
    mock_redis.get.return_value = "PROCESSING"
    
    with patch("backend.workflow.chat_workflow.redis_client.init", return_value=mock_redis), \
         patch("backend.workflow.chat_workflow.MessageResponse.model_validate", return_value=MagicMock()), \
         patch("backend.workflow.chat_workflow.ChatQueryResponse", return_value=MagicMock()), \
         patch("backend.utils.tokenizer.tiktoken.get_encoding", return_value=MagicMock()):
        
        workflow = ChatWorkflow(uow, llm_service, prompt_manager)
        
        user_id = uuid.uuid4()
        client_req_id = "test-req-123"
        
        # 模拟环境
        mock_user = MagicMock(used_tokens=0, max_tokens=1000)
        uow.users.get = AsyncMock(return_value=mock_user)
        uow.__aenter__.return_value = uow
        
        # 1. 第一个请求
        print("First request...")
        try:
            await workflow.handle_query(user_id, "hello", client_request_id=client_req_id)
        except Exception:
            pass
            
        # 2. 第二个并发请求
        print("Second request...")
        try:
            await workflow.handle_query(user_id, "hello", client_request_id=client_req_id)
        except Exception as e:
            print(f"Caught second request error: {e}")
            assert "正在加速计算中" in str(e)
            print("Idempotency test passed!")

async def test_token_quota():
    print("\nTesting Token Quota...")
    uow = MagicMock()
    llm_service = AsyncMock()
    
    workflow = ChatWorkflow(uow, llm_service)
    user_id = uuid.uuid4()
    
    # Mock 用户已欠费 (used >= max)
    mock_user = MagicMock(used_tokens=1000, max_tokens=1000)
    uow.users.get = AsyncMock(return_value=mock_user)
    uow.__aenter__.return_value = uow
    
    print("Quota check request...")
    try:
        await workflow.handle_query(user_id, "hello")
    except Exception as e:
        print(f"Caught quota error: {e}")
        assert "Token 余额不足" in str(e)
        print("Token quota test passed!")

async def test_token_recording():
    print("\nTesting Token Recording...")
    uow = MagicMock()
    llm_service = AsyncMock()
    
    llm_service.generate_response.return_value = LLMResultDTO(
        content="This is a test response",
        success=True,
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=100
    )
    
    workflow = ChatWorkflow(uow, llm_service)
    user_id = uuid.uuid4()
    
    # Mock environment
    mock_user = MagicMock(used_tokens=0, max_tokens=1000)
    uow.users.get = AsyncMock(return_value=mock_user)
    uow.__aenter__.return_value = uow
    
    # Mock session and assistant message
    session = MagicMock(id=uuid.uuid4(), title="Test Session")
    assistant_msg = MagicMock(id=uuid.uuid4())
    
    with patch("backend.services.chat_service.SessionManager.ensure_session", AsyncMock(return_value=session)), \
         patch("backend.services.chat_service.SessionManager.create_user_message", AsyncMock()), \
         patch("backend.services.chat_service.SessionManager.create_assistant_message", AsyncMock(return_value=assistant_msg)), \
         patch("backend.services.chat_service.SessionManager.get_session_messages", AsyncMock(return_value=[])), \
         patch("backend.workflow.chat_workflow.MessageResponse.model_validate", return_value=MagicMock()), \
         patch("backend.workflow.chat_workflow.ChatQueryResponse", return_value=MagicMock()), \
         patch("backend.workflow.chat_workflow.ChatMessageUpdater", MagicMock()) as mock_updater_cls, \
         patch("backend.utils.tokenizer.tiktoken.get_encoding", return_value=MagicMock()):
        
        mock_updater = mock_updater_cls.return_value
        mock_updater.update_as_success = AsyncMock(return_value=assistant_msg)
        uow.users.increment_used_tokens = AsyncMock()

        print("Recording request...")
        await workflow.handle_query(user_id, "hello")
        
        call_args = mock_updater.update_as_success.call_args[1]
        print(f"Recorded tokens_input: {call_args.get('tokens_input')}")
        print(f"Recorded tokens_output: {call_args.get('tokens_output')}")
        
        assert call_args.get('tokens_input') is not None
        assert call_args.get('tokens_output') == 5
        
        # Verify user quota was updated
        uow.users.increment_used_tokens.assert_called_once()
        print("Token recording test passed!")

async def main():
    await test_idempotency()
    await test_token_quota()
    await test_token_recording()

if __name__ == "__main__":
    asyncio.run(main())
