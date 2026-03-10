import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action_type: str
    status: str
    progress: int
    payload: dict
    error_log: str | None = None
    created_at: datetime
    updated_at: datetime
