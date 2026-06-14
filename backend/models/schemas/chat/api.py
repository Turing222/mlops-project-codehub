"""HTTP API schemas.

职责：定义 API 层专属的请求体校验与响应序列化。
边界：只负责输入输出的格式转换，依赖 dto.py 获取枚举等基础类型。
"""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.models.enums import MessageStatus
from backend.models.schemas.chat.context_routing import ContextMode
from backend.models.schemas.chat.params import LLMExtraBody

QueryStr = Annotated[
    str, Field(min_length=1, max_length=5000, description="用户查询内容")
]
SessionTitleStr = Annotated[
    str, Field(min_length=1, max_length=50, description="会话标题")
]


class QuerySentRequest(BaseModel):
    """用户发送查询的请求体。"""

    query: QueryStr
    session_id: uuid.UUID | None = Field(None, description="会话 ID，为空则创建新会话")
    kb_id: uuid.UUID | None = Field(None, description="关联的知识库 ID")
    client_request_id: str | None = Field(
        None,
        max_length=64,
        description="客户端生成的唯一请求 ID，用于幂等控制",
    )
    enable_external_context: bool = Field(
        False,
        description="允许 Planner 按需检索外部上下文",
    )
    context_mode: ContextMode | None = Field(
        None,
        description="上下文路由模式：auto/kb_only/web_only/off；为空时兼容 enable_external_context",
    )
    extra_body: LLMExtraBody | None = Field(
        None, description="透传到 LLM API 的受控额外参数，如 thinking 模式控制"
    )

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("查询内容不能为空白字符")
        return stripped

    model_config = ConfigDict(str_strip_whitespace=True)


class SessionUpdateRequest(BaseModel):
    """更新会话信息（如标题）"""

    title: SessionTitleStr | None = None

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )


class MessageResponse(BaseModel):
    """单条消息的 API 响应"""

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    status: MessageStatus
    latency_ms: int | None = None
    search_context: dict | None = None
    message_metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionResponse(BaseModel):
    """单个会话的 API 响应"""

    id: uuid.UUID
    title: str
    user_id: uuid.UUID
    kb_id: uuid.UUID | None = None
    llm_config: dict = Field(default_factory=dict)
    total_tokens: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionListResponse(BaseModel):
    """会话列表的分页响应"""

    items: list[SessionResponse]
    total: int = Field(..., ge=0, description="总记录数")
    skip: int
    limit: int


class ChatQueryResponse(BaseModel):
    """
    查询接口的完整响应。
    包含会话信息和 AI 回复消息。
    """

    session_id: uuid.UUID
    session_title: str
    answer: MessageResponse

    model_config = ConfigDict(from_attributes=True)


class SessionDetailResponse(BaseModel):
    """会话详情（含历史消息列表）"""

    session: SessionResponse
    messages: list[MessageResponse]
    total_messages: int
