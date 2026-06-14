"""Repo analysis worker workflow.

Worker-side boundary: collect repository evidence, run analysis, and persist results.
"""

import uuid

from backend.application.repo_analysis.analyzer import RepoCredibilityAnalyzer
from backend.application.repo_analysis.evidence import RepoEvidenceExtractor
from backend.application.repo_analysis.github import (
    GitHubRepoCollector,
    parse_github_repo_url,
)
from backend.application.repo_analysis.renderer import RepoReportRenderer
from backend.core.exceptions import AppException
from backend.models.schemas.repo_analysis_schema import (
    RepoReportPayload,
    RepoSnapshot,
    RepoSubject,
)
from backend.observability.trace_utils import trace_span
from backend.services.repo_analysis_service import RepoAnalysisService
from backend.services.task_service import TaskService


class RepoAnalysisWorkerWorkflow:
    """Worker-side README-only analysis workflow."""

    def __init__(
        self,
        *,
        repo_analysis_service: RepoAnalysisService,
        task_service: TaskService,
        collector: GitHubRepoCollector | None = None,
        extractor: RepoEvidenceExtractor | None = None,
        analyzer: RepoCredibilityAnalyzer | None = None,
        renderer: RepoReportRenderer | None = None,
    ) -> None:
        self.repo_analysis_service = repo_analysis_service
        self.task_service = task_service
        self.collector = collector or GitHubRepoCollector()
        self.extractor = extractor or RepoEvidenceExtractor()
        self.analyzer = analyzer or RepoCredibilityAnalyzer()
        self.renderer = renderer or RepoReportRenderer()

    async def run(self, *, run_id: uuid.UUID, task_id: uuid.UUID) -> None:
        async with self.repo_analysis_service.uow:
            run = await self.repo_analysis_service.get_run(run_id)
            if run is None:
                raise ValueError("repo analysis run not found")
            await self.repo_analysis_service.mark_running(run_id=run_id)
            await self.task_service.mark_processing(task_id=task_id, progress=10)

        try:
            with trace_span(
                "repo_analysis.readme.collect",
                {"repo_analysis.run_id": str(run_id)},
            ):
                parsed = parse_github_repo_url(run.repo_url)
                collected = await self.collector.collect(parsed)
                subject = RepoSubject.model_validate(collected.subject)
                snapshot = RepoSnapshot.model_validate(collected.snapshot)

            evidence = self.extractor.extract(
                readme_text=collected.readme_text,
                snapshot=snapshot.model_dump(mode="json"),
            )
            assessment, generated_by = await self.analyzer.analyze(
                subject=subject.model_dump(mode="json"),
                snapshot=snapshot.model_dump(mode="json"),
                evidence=evidence,
            )
            markdown = self.renderer.render_markdown(
                subject=subject.model_dump(mode="json"),
                snapshot=snapshot.model_dump(mode="json"),
                evidence=evidence,
                assessment=assessment,
                generated_by=generated_by,
            )
            report = RepoReportPayload(
                structured=assessment,
                markdown=markdown,
                generated_by=generated_by,
            )

            async with self.repo_analysis_service.uow:
                await self.repo_analysis_service.save_success(
                    run_id=run_id,
                    subject=subject,
                    snapshot=snapshot,
                    evidence=evidence,
                    report=report,
                )
                await self.task_service.mark_completed(task_id=task_id, progress=100)
        except Exception as exc:
            await self._mark_failed(run_id=run_id, task_id=task_id, exc=exc)
            raise

    async def _mark_failed(
        self,
        *,
        run_id: uuid.UUID,
        task_id: uuid.UUID,
        exc: Exception,
    ) -> None:
        message = exc.message if isinstance(exc, AppException) else str(exc)
        async with self.repo_analysis_service.uow:
            await self.repo_analysis_service.mark_failed(
                run_id=run_id,
                error_message=message or "仓库分析失败",
            )
            await self.task_service.mark_failed(
                task_id=task_id,
                error_log=message or "仓库分析失败",
            )
