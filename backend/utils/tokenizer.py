import tiktoken
from backend.core.config import settings

def count_tokens(text: str, model: str = None) -> int:
    """
    计算文本的 Token 数
    """
    if not text:
        return 0
    
    # 默认使用 cl100k_base (gpt-3.5-turbo, gpt-4)
    # 对于 qwen 等模型，tiktoken 可能不完全准确，但在没有专用分词器时是通用方案
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # 降级方案：按字符数估算 (约 1 token = 1.5 字符)
        return len(text) // 2 + 1

def count_messages_tokens(messages: list[dict], model: str = None) -> int:
    """
    计算消息列表的总 Token 数
    """
    total = 0
    for msg in messages:
        total += count_tokens(msg.get("content", ""))
        total += 4  # 每条消息的元数据开销
    total += 3  # 对话整体开销
    return total
