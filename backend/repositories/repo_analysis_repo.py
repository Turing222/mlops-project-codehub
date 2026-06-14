"""Repo analysis persistence repository.

职责：封装 repo analysis run/result 的创建、状态流转和查询。
边界：不投递 TaskIQ、不调用 GitHub 或 LLM。
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.repo_analysis import (
    RepoAnalysisResult,
    RepoAnalysisRun,
    RepoAnalysisStatus,
)


class RepoAnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_run(
        self,
        *,
        user_id: uuid.UUID,
        repo_url: str,
        owner: str,
        repo: str,
        rubric_version: str,
    ) -> RepoAnalysisRun:
        run = RepoAnalysisRun(
            user_id=user_id,
            repo_url=repo_url,
            owner=owner,
            repo=repo,
            status=RepoAnalysisStatus.PENDING,
            rubric_version=rubric_version,
        )
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def get_run(self, run_id: uuid.UUID) -> RepoAnalysisRun | None:
        return await self.session.get(RepoAnalysisRun, run_id)

    async def get_run_for_user(
        self, *, run_id: uuid.UUID, user_id: uuid.UUID
    ) -> RepoAnalysisRun | None:
        stmt = select(RepoAnalysisRun).where(
            RepoAnalysisRun.id == run_id,
            RepoAnalysisRun.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_task_id(
        self, *, run_id: uuid.UUID, task_id: uuid.UUID
    ) -> RepoAnalysisRun | None:
        run = await self.get_run(run_id)
        if run is None:
            return None
        run.task_id = task_id
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def mark_running(self, *, run_id: uuid.UUID) -> RepoAnalysisRun | None:
        return await self._update_status(
            run_id=run_id, status=RepoAnalysisStatus.RUNNING
        )

    async def mark_failed(
        self, *, run_id: uuid.UUID, error_message: str
    ) -> RepoAnalysisRun | None:
        return await self._update_status(
            run_id=run_id,
            status=RepoAnalysisStatus.FAILED,
            error_message=error_message[:5000],
        )

    async def mark_succeeded(self, *, run_id: uuid.UUID) -> RepoAnalysisRun | None:
        return await self._update_status(
            run_id=run_id, status=RepoAnalysisStatus.SUCCEEDED
        )

    async def create_result(
        self,
        *,
        run_id: uuid.UUID,
        subject: dict[str, Any],
        snapshot: dict[str, Any],
        evidence: dict[str, Any],
        structured_report: dict[str, Any],
        markdown_report: str,
        generated_by: str,
    ) -> RepoAnalysisResult:
        result = RepoAnalysisResult(
            run_id=run_id,
            subject=subject,
            snapshot=snapshot,
            evidence=evidence,
            structured_report=structured_report,
            markdown_report=markdown_report,
            generated_by=generated_by,
        )
        self.session.add(result)
        await self.session.flush()
        await self.session.refresh(result)
        return result

    async def get_result_for_run(self, run_id: uuid.UUID) -> RepoAnalysisResult | None:
        stmt = select(RepoAnalysisResult).where(RepoAnalysisResult.run_id == run_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _update_status(
        self,
        *,
        run_id: uuid.UUID,
        status: RepoAnalysisStatus,
        error_message: str | None = None,
    ) -> RepoAnalysisRun | None:
        run = await self.get_run(run_id)
        if run is None:
            return None
        run.status = status
        run.error_message = error_message
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run
