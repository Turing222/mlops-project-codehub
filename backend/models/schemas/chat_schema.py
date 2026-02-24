"""
Chat Schema 层 — 企业级 Pydantic 模型

分层设计：
- Reusable Types: 可复用的类型约束
- Base Schemas: 基础字段组合
- Request Schemas: API 输入校验
- Response Schemas: API 输出序列化
- Internal DTOs: 服务间数据流转对象
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ============================================================
# --- Reusable Types (提升代码一致性) ---
# ============================================================

QueryStr = Annotated[
    str, Field(min_length=1, max_length=5000, description="用户查询内容")
]
SessionTitleStr = Annotated[
    str, Field(min_length=1, max_length=50, description="会话标题")
]


class MessageRole(StrEnum):
    """消息角色枚举，用于 Schema 层的类型安全"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageStatusEnum(StrEnum):
    """消息状态枚举，与 ORM 层的 MessageStatus 保持同步"""

    THINKING = "thinking"
    STREAMING = "streaming"
    SUCCESS = "success"
    FAILED = "failed"


# ============================================================
# --- Request Schemas (输入控制) ---
# ============================================================


class QuerySentRequest(BaseModel):
    """
    用户发送查询的请求体。
    session_id 为空时自动创建新会话。
    """

    query: QueryStr
    session_id: uuid.UUID | None = Field(None, description="会话 ID，为空则创建新会话")
    kb_id: uuid.UUID | None = Field(None, description="关联的知识库 ID")

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("查询内容不能为空白字符")
        return stripped

    model_config = ConfigDict(str_strip_whitespace=True)


class SessionListRequest(BaseModel):
    """获取会话列表的查询参数"""

    skip: int = Field(default=0, ge=0, description="跳过的记录数")
    limit: int = Field(default=20, ge=1, le=100, description="每页记录数")


class SessionHistoryRequest(BaseModel):
    """获取会话历史消息的请求参数"""

    session_id: uuid.UUID = Field(..., description="会话 ID")
    skip: int = Field(default=0, ge=0, description="跳过的记录数")
    limit: int = Field(default=100, ge=1, le=500, description="每页记录数")


class SessionUpdateRequest(BaseModel):
    """更新会话信息（如标题）"""

    title: SessionTitleStr | None = None

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )


# ============================================================
# --- Response Schemas (输出控制) ---
# ============================================================


class MessageResponse(BaseModel):
    """单条消息的 API 响应"""

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    status: MessageStatusEnum
    latency_ms: int | None = None
    search_context: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionResponse(BaseModel):
    """单个会话的 API 响应"""

    id: uuid.UUID
    title: str
    user_id: uuid.UUID
    kb_id: uuid.UUID | None = None
    model_config_data: dict = Field(default_factory=dict, alias="model_config")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


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


# ============================================================
# --- Internal DTOs (服务间数据流转，不暴露给 API) ---
# ============================================================


class LLMQueryDTO(BaseModel):
    """传递给 LLMService 的查询参数"""

    session_id: uuid.UUID
    query_text: str
    conversation_history: list[dict] = Field(default_factory=list)


class LLMResultDTO(BaseModel):
    """LLMService 返回的结果"""

    content: str
    latency_ms: int | None = None
    success: bool = True
    error_message: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class MessageCreateDTO(BaseModel):
    """服务层创建消息的内部 DTO"""

    session_id: uuid.UUID
    role: MessageRole
    content: str
    status: MessageStatusEnum = MessageStatusEnum.SUCCESS
    latency_ms: int | None = None


class MessageUpdateDTO(BaseModel):
    """服务层更新消息的内部 DTO"""

    message_id: uuid.UUID
    status: MessageStatusEnum
    content: str | None = None
    latency_ms: int | None = None
