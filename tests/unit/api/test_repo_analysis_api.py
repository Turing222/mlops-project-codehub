"""Repo analysis API unit tests.

职责：验证 endpoint 参数传递和 read context 查询；边界：直接调用 endpoint，不启动 FastAPI app。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.v1.endpoint import repo_analysis_api
from backend.models.schemas.repo_analysis_schema import (
    RepoAnalysisRunPayload,
    RepoAnalysisRunResponse,
    RepoAnalysisSubmitRequest,
    RepoAnalysisSubmitResponse,
)

pytestmark = pytest.mark.asyncio


class AsyncContextManagerMock:
    async def __aenter__(self) -> None:
        pass

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        pass


async def test_submit_readme_check_delegates_to_workflow() -> None:
    user_id = uuid.uuid4()
    expected = RepoAnalysisSubmitResponse(
        run_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        status="pending",
    )
    workflow = SimpleNamespace(submit=AsyncMock(return_value=expected))

    result = await repo_analysis_api.submit_readme_check(
        payload=RepoAnalysisSubmitRequest(repo_url="https://github.com/openai/codex"),
        current_user=SimpleNamespace(id=user_id),
        workflow=workflow,
    )

    assert result == expected
    workflow.submit.assert_awaited_once_with(
        repo_url="https://github.com/openai/codex",
        user_id=user_id,
    )


async def test_get_repo_analysis_run_uses_read_context() -> None:
    user_id = uuid.uuid4()
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    expected = RepoAnalysisRunResponse(
        run=RepoAnalysisRunPayload(
            id=run_id,
            status="pending",
            repo_url="https://github.com/openai/codex",
            owner="openai",
            repo="codex",
            task_id=None,
            rubric_version="readme-only-v1",
            error_message=None,
            created_at=now,
            updated_at=now,
        )
    )
    service = SimpleNamespace(
        read=MagicMock(return_value=AsyncContextManagerMock()),
        get_user_run_response=AsyncMock(return_value=expected),
    )

    result = await repo_analysis_api.get_repo_analysis_run(
        run_id=run_id,
        current_user=SimpleNamespace(id=user_id),
        service=service,
    )

    assert result == expected
    service.read.assert_called_once()
    service.get_user_run_response.assert_awaited_once_with(
        run_id=run_id,
        user_id=user_id,
    )
