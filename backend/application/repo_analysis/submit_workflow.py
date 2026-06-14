"""Repo analysis submit workflow.

Web-side boundary: create the run/task and dispatch worker execution.
"""

import uuid

from backend.application.repo_analysis.github import parse_github_repo_url
from backend.contracts.interfaces import AbstractTaskDispatcher
from backend.models.schemas.repo_analysis_schema import (
    RUBRIC_VERSION_README_ONLY,
    RepoAnalysisSubmitResponse,
)
from backend.observability.trace_utils import inject_trace_context
from backend.services.repo_analysis_service import RepoAnalysisService
from backend.services.task_service import TaskService


class RepoAnalysisSubmitWorkflow:
    """Web-side workflow: create run/task and dispatch worker task."""

    def __init__(
        self,
        *,
        repo_analysis_service: RepoAnalysisService,
        task_service: TaskService,
        dispatcher: AbstractTaskDispatcher,
    ) -> None:
        self.repo_analysis_service = repo_analysis_service
        self.task_service = task_service
        self.dispatcher = dispatcher

    async def submit(
        self,
        *,
        repo_url: str,
        user_id: uuid.UUID,
    ) -> RepoAnalysisSubmitResponse:
        parsed = parse_github_repo_url(repo_url)
        async with self.repo_analysis_service.uow:
            run = await self.repo_analysis_service.create_run(
                user_id=user_id,
                repo_url=parsed.url,
                owner=parsed.owner,
                repo=parsed.repo,
                rubric_version=RUBRIC_VERSION_README_ONLY,
            )
            task = await self.task_service.create_repo_analysis_task(
                run_id=run.id,
                repo_url=parsed.url,
                owner=parsed.owner,
                repo=parsed.repo,
                user_id=user_id,
            )
            await self.repo_analysis_service.set_task_id(run_id=run.id, task_id=task.id)

        try:
            await self.dispatcher.enqueue_repo_analysis(
                str(run.id),
                str(task.id),
                inject_trace_context(),
            )
        except Exception:
            async with self.repo_analysis_service.uow:
                await self.repo_analysis_service.mark_failed(
                    run_id=run.id,
                    error_message="分析任务投递失败，请稍后重试",
                )
                await self.task_service.mark_failed(
                    task_id=task.id,
                    error_log="分析任务投递失败，请稍后重试",
                )
            raise

        return RepoAnalysisSubmitResponse(
            run_id=run.id,
            task_id=task.id,
            status="pending",
        )
