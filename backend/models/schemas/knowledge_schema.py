"""Knowledge API response schemas.

职责：定义知识库上传任务和文件状态的响应结构。
边界：本模块不处理文件存储、解析或向量化。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeUploadResponse(BaseModel):
    task_id: uuid.UUID = Field(description="异步入库任务 ID")
    file_id: uuid.UUID = Field(description="知识库文件 ID")
    kb_id: uuid.UUID | None = Field(default=None, description="知识库 ID")
    file_status: str = Field(description="文件处理状态")
    task_status: str = Field(description="任务状态")
    deduplicated: bool = Field(default=False, description="是否复用已就绪的同内容文件")


class KnowledgeFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    filename: str
    file_size: int
    content_sha256: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
