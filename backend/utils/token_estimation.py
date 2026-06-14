"""Token estimation helpers.

职责：为 prompt 预算和信用预检提供保守 token 估算。
边界：本模块只做本地估算，不向模型服务请求真实 usage。
失败处理：真实 usage 由 provider 返回后在调用方覆盖本估算。

位置：放在 backend/utils/ 而非 backend/ai/core/ 下，
因为 web 镜像不安装 jinja2，而 backend.ai.core.__init__ 的导入链
会拉入 prompt_manager → jinja2，导致 web 侧无法导入。
"""

import math
import re
from collections.abc import Sequence
from typing import Any

from backend.models.schemas.chat.dto import ConversationMessage

CJK_RANGES = (
    ("\u3400", "\u4dbf"),
    ("\u4e00", "\u9fff"),
    ("\uf900", "\ufaff"),
)
ESTIMATE_SAFETY_MULTIPLIER = 1.2
MESSAGE_OVERHEAD_TOKENS = 3
REPLY_PRIMER_TOKENS = 3
OTHER_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)


def _is_cjk(char: str) -> bool:
    return any(start <= char <= end for start, end in CJK_RANGES)


def estimate_tokens(text: str, model: str | None = None) -> int:
    """Conservatively estimate tokens for mixed CJK/Latin text."""
    if not text:
        return 0

    cjk_chars = sum(1 for char in text if _is_cjk(char))
    other_chars = len(text) - cjk_chars
    lexical_tokens = len(OTHER_TOKEN_RE.findall(text))
    estimated = max(
        cjk_chars + math.ceil(other_chars / 3),
        cjk_chars + lexical_tokens,
        math.ceil(len(text) / 3),
    )
    return max(1, math.ceil(estimated * ESTIMATE_SAFETY_MULTIPLIER))


def estimate_messages_tokens(
    messages: Sequence[dict[str, Any] | ConversationMessage],
    model: str | None = None,
) -> int:
    """Estimate chat messages; this is not provider-specific exact counting."""
    if not messages:
        return 0

    total = 0
    for msg in messages:
        total += MESSAGE_OVERHEAD_TOKENS
        total += estimate_tokens(msg["content"], model)
        total += estimate_tokens(msg["role"], model)

    return total + REPLY_PRIMER_TOKENS


count_tokens = estimate_tokens
count_messages_tokens = estimate_messages_tokens
