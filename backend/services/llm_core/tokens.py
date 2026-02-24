"""
Token 计数工具

提供 Token 计算能力，优先使用 tiktoken，不可用时 fallback 到字符估算。
"""

import logging

logger = logging.getLogger(__name__)

# --- tiktoken 延迟加载 ---
_tiktoken_available = False
_encoding_cache: dict = {}

try:
    import tiktoken

    _tiktoken_available = True
    logger.info("tiktoken 加载成功，将使用精确的 Token 计算")
except ImportError:
    logger.warning("tiktoken 未安装，将使用字符估算法 (len // 3)")


def _get_encoding(model: str):
    """获取或缓存指定模型的 tiktoken 编码器"""
    if model not in _encoding_cache:
        try:
            _encoding_cache[model] = tiktoken.encoding_for_model(model)
        except KeyError:
            # 模型名不在 tiktoken 的注册表中，使用通用编码器
            logger.debug("模型 '%s' 无专用编码器，使用 cl100k_base", model)
            _encoding_cache[model] = tiktoken.get_encoding("cl100k_base")
    return _encoding_cache[model]


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    计算单条文本的 Token 数

    Args:
        text: 待计算的文本
        model: 模型名称（用于选择 tokenizer）

    Returns:
        Token 数量
    """
    if not text:
        return 0

    if _tiktoken_available:
        encoding = _get_encoding(model)
        return len(encoding.encode(text))

    # Fallback: 中文约 1 字 ≈ 1~2 token, 英文约 4 字符 ≈ 1 token
    # 取中间值 len // 3 作为保守估算
    return max(1, len(text) // 3)


def count_messages_tokens(
    messages: list[dict],
    model: str = "gpt-4",
) -> int:
    """
    计算完整消息列表的 Token 数

    遵循 OpenAI 的消息格式计算规则：
    每条消息有固定的 overhead (role + formatting ≈ 4 tokens)

    Args:
        messages: [{"role": "...", "content": "..."}] 格式的消息列表
        model: 模型名称

    Returns:
        总 Token 数量
    """
    if not messages:
        return 0

    tokens_per_message = 4  # 每条消息的固定开销

    total = 0
    for msg in messages:
        total += tokens_per_message
        total += count_tokens(msg.get("content", ""), model)
        total += count_tokens(msg.get("role", ""), model)

    total += 2  # 回复的起始 token 开销
    return total
