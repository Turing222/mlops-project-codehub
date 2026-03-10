import logging

from langfuse import observe

from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.core.redis import redis_client
from backend.core.task_broker import broker
from backend.models.schemas.chat_schema import LLMQueryDTO

logger = logging.getLogger(__name__)

@broker.task(task_name="generate_llm_stream")
@observe(as_type="generation")
async def generate_llm_stream_task(llm_query_dict: dict, channel: str):
    logger.info(f"Taskiq Worker 开始处理流式请求: {channel}")
    
    # 获取 redis 客户端用于发布消息
    redis = await redis_client.init()
    
    llm_service = LLMProviderFactory.create()
    llm_query = LLMQueryDTO(**llm_query_dict)
    
    try:
        # 这个就是原生的 asyncio 生成器
        async for chunk in llm_service.stream_response(llm_query):
            await redis.publish(channel, chunk)
            
        await redis.publish(channel, "[DONE]")
        logger.info(f"Taskiq Worker 成功结束流式处理: {channel}")
    except Exception as e:
        logger.error(f"Taskiq 调用 LLM 失败: {e}", exc_info=True)
        # 向主程序报错
        await redis.publish(channel, f"[ERROR]{str(e)}")
