"""Application use-case commands.

职责：封装单个用例（如一次查询）的完整意图。
边界：连接 HTTP API 层与 Workflow 层，将散装的 HTTP 请求参数聚合为内部领域可以理解的命令对象。
"""

import uuid

from pydantic import BaseModel

from backend.models.schemas.chat.context_routing import ContextMode


class ChatQueryCommand(BaseModel):
    """用例入口：一次对话查询的完整意图。"""

    user_id: uuid.UUID
    query_text: str
    session_id: uuid.UUID | None = None
    kb_id: uuid.UUID | None = None
    client_request_id: str | None = None
    enable_external_context: bool = False
    context_mode: ContextMode | None = None
    extra_body: dict[str, object] | None = None
