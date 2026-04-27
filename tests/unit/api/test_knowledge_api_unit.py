from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from backend.api.v1.endpoint import knowledge_api
from backend.models.schemas.knowledge_schema import KnowledgeUploadResponse


@pytest.mark.asyncio
async def test_upload_file_stream_uses_stream_workflow():
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)
    expected = KnowledgeUploadResponse(
        task_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        kb_id=kb_id,
        file_status="uploaded",
        task_status="pending",
    )
    upload_workflow = SimpleNamespace(
        submit_stream_ingestion=AsyncMock(return_value=expected)
    )

    result = await knowledge_api.upload_file_stream(
        kb_id=kb_id,
        file=upload_file,
        current_user=SimpleNamespace(id=user_id),
        upload_workflow=upload_workflow,
    )

    assert result == expected
    upload_workflow.submit_stream_ingestion.assert_awaited_once_with(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )


@pytest.mark.asyncio
async def test_upload_file_stream_to_default_kb_uses_default_workflow():
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)
    expected = KnowledgeUploadResponse(
        task_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        file_status="uploaded",
        task_status="pending",
    )
    upload_workflow = SimpleNamespace(
        submit_default_stream_ingestion=AsyncMock(return_value=expected)
    )

    result = await knowledge_api.upload_file_stream_to_default_kb(
        file=upload_file,
        current_user=SimpleNamespace(id=user_id),
        upload_workflow=upload_workflow,
    )

    assert result == expected
    upload_workflow.submit_default_stream_ingestion.assert_awaited_once_with(
        user_id=user_id,
        upload_file=upload_file,
    )
