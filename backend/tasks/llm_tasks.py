import logging

from langfuse import observe

from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.core.exceptions import AppError
from backend.core.redis import redis_client
from backend.core.task_broker import broker
from backend.core.trace_utils import set_span_attributes, trace_span, use_trace_context
from backend.models.schemas.chat_schema import LLMQueryDTO

logger = logging.getLogger(__name__)


@broker.task(task_name="generate_llm_stream")
@observe(as_type="generation")
async def generate_llm_stream_task(
    llm_query_dict: dict,
    channel: str,
    trace_context: dict[str, str] | None = None,
):
    with use_trace_context(trace_context):
        await _generate_llm_stream_task(llm_query_dict, channel)


async def _generate_llm_stream_task(llm_query_dict: dict, channel: str):
    logger.info("Taskiq Worker 开始处理流式请求: %s", channel)

    with trace_span(
        "taskiq.llm_stream.setup",
        {
            "redis.channel": channel,
            "llm.provider": None,
        },
    ):
        redis = await redis_client.init()
        llm_service = LLMProviderFactory.create()
        llm_query = LLMQueryDTO(**llm_query_dict)

    try:
        with trace_span(
            "taskiq.llm_stream.publish_chunks",
            {
                "redis.channel": channel,
                "chat.session_id": llm_query.session_id,
                "llm.provider": getattr(llm_service, "provider_name", "unknown"),
                "gen_ai.request.model": getattr(llm_service, "model_name", "unknown"),
            },
        ) as span:
            chunk_count = 0
            char_count = 0
            async for chunk in llm_service.stream_response(llm_query):
                chunk_count += 1
                char_count += len(chunk)
                await redis.publish(channel, chunk)
            set_span_attributes(
                span,
                {
                    "llm.response.chunk_count": chunk_count,
                    "llm.response.char_count": char_count,
                },
            )
        logger.info("Taskiq Worker 成功结束流式处理: %s", channel)
    except AppError as exc:
        logger.warning("Taskiq 调用 LLM 业务异常: %s", exc)
        # 向主程序回传业务错误，供上游统一处理
        await redis.publish(channel, f"[ERROR]{exc}")
    except Exception:
        logger.exception("Taskiq 调用 LLM 系统异常")
        # 向主程序报错
        await redis.publish(channel, "[ERROR]服务暂时不可用，请稍后重试")
    finally:
        await redis.publish(channel, "[DONE]")
