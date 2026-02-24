import asyncio
import time
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from backend.workflow.chat_workflow import ChatWorkflow
from backend.models.schemas.chat_schema import LLMQueryDTO
from backend.core.config import settings

async def test_workflow_concurrency():
    # 模拟并发配置
    with patch("backend.workflow.chat_workflow.settings.LLM_MAX_CONCURRENCY", 2), \
         patch("backend.workflow.chat_workflow.settings.DB_MAX_CONCURRENCY", 2):
        
        # 重置 Workflow 的信号量
        ChatWorkflow._llm_semaphore = asyncio.Semaphore(2)
        ChatWorkflow._db_semaphore = asyncio.Semaphore(2)

        # 模拟依赖
        uow = MagicMock()
        uow.__aenter__.return_value = uow
        uow.__aexit__.return_value = None
        
        llm_service = MagicMock()
        
        # 模拟流式返回，耗时 0.5s
        async def mock_stream(*args, **kwargs):
            await asyncio.sleep(0.5)
            yield '{"type":"chunk", "content":"hello"}'
            
        llm_service.stream_response = MagicMock(side_effect=mock_stream)
        
        # 模拟 SessionManager 等内部调用，防止报错
        with patch("backend.workflow.chat_workflow.SessionManager") as mock_sm, \
             patch("backend.workflow.chat_workflow.ChatMessageUpdater") as mock_up, \
             patch("backend.workflow.chat_workflow.PromptManager") as mock_pm:
            
            mock_sm_inst = mock_sm.return_value
            mock_sm_inst.ensure_session = AsyncMock(return_value=MagicMock(id=uuid.uuid4(), title="test"))
            mock_sm_inst.create_user_message = AsyncMock()
            mock_sm_inst.create_assistant_message = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            mock_sm_inst.get_session_messages = AsyncMock(return_value=[])
            
            mock_up_inst = mock_up.return_value
            mock_up_inst.update_as_success = AsyncMock()
            mock_up_inst.update_as_failed = AsyncMock()
            
            mock_pm_inst = mock_pm.return_value
            mock_pm_inst.assemble = MagicMock(return_value=MagicMock(messages=[], total_tokens=0, history_rounds_used=0, truncated=False))
            
            workflow = ChatWorkflow(uow, llm_service)
            
            user_id = uuid.uuid4()
            start_time = time.time()
            
            # 同时发起 4 个流式请求
            # 注意：handle_query_stream 是异步生成器，我们需要消费它
            async def consume_stream():
                async for _ in workflow.handle_query_stream(user_id=user_id, query_text="hello"):
                    pass

            tasks = [consume_stream() for _ in range(4)]
            await asyncio.gather(*tasks)
            
            end_time = time.time()
            total_time = end_time - start_time
            print(f"Total time for 4 workflow requests with concurrency 2: {total_time:.2f}s")
            
            # 预期时间应该是大约 1.0s (2组并发，每组0.5s)
            assert 0.9 <= total_time <= 1.5

if __name__ == "__main__":
    asyncio.run(test_workflow_concurrency())
