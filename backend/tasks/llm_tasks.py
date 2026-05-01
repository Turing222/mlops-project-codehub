"""LLM streaming TaskIQ tasks.

职责：在 worker 中调用 LLM provider，并通过 Redis Pub/Sub 把 chunk 发回主进程。
边界：本模块不创建会话或更新消息状态；主 workflow 负责消费和持久化。
失败处理：业务和系统异常都会发布 [ERROR]，finally 始终发布 [DONE] 解除等待方阻塞。
"""

import logging
from typing import Any

from langfuse import observe

from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.core.exceptions import AppException
from backend.core.redis import redis_client
from backend.core.task_broker import broker
from backend.core.trace_utils import set_span_attributes, trace_span, use_trace_context
from backend.models.schemas.chat_schema import LLMQueryDTO

logger = logging.getLogger(__name__)


@broker.task(task_name="generate_llm_stream")
@observe(as_type="generation")
async def generate_llm_stream_task(
    llm_query_dict: dict[str, Any],
    channel: str,
    trace_context: dict[str, str] | None = None,
) -> None:
    """TaskIQ 入口：恢复 trace context 后发布 LLM 流式输出。"""
    with use_trace_context(trace_context):
        await _generate_llm_stream_task(llm_query_dict, channel)


async def _generate_llm_stream_task(
    llm_query_dict: dict[str, Any],
    channel: str,
) -> None:
    logger.info("Taskiq Worker 开始处理流式请求: %s", channel)

    with trace_span(
        "taskiq.llm_stream.setup",
        {
            "redis.channel": channel,
            "llm.provider": None,
        },
    ):
        redis_connection = await redis_client.init()
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
                await redis_connection.publish(channel, chunk)
            set_span_attributes(
                span,
                {
                    "llm.response.chunk_count": chunk_count,
                    "llm.response.char_count": char_count,
                },
            )
        logger.info("Taskiq Worker 成功结束流式处理: %s", channel)
    except AppException as exc:
        logger.warning("Taskiq 调用 LLM 业务异常: %s", exc)
        # 主 workflow 只监听 Pub/Sub，业务错误必须通过 channel 回传。
        await redis_connection.publish(channel, f"[ERROR]{exc}")
    except Exception:
        logger.exception("Taskiq 调用 LLM 系统异常")
        # 系统异常返回固定文案，避免把 provider 内部错误暴露给前端。
        await redis_connection.publish(channel, "[ERROR]服务暂时不可用，请稍后重试")
    finally:
        await redis_connection.publish(channel, "[DONE]")
