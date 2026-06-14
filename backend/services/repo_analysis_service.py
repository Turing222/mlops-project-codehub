"""Repo analysis service.

职责：维护 repo analysis run/result 的事务性状态与访问控制。
边界：不调用 GitHub、不调用 LLM、不投递 TaskIQ。
"""

import uuid

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import app_not_found
from backend.models.orm.repo_analysis import RepoAnalysisRun, RepoAnalysisStatus
from backend.models.schemas.repo_analysis_schema import (
    README_ONLY_CAVEAT,
    ReadmeCredibilityAssessment,
    RepoAnalysisRunPayload,
    RepoAnalysisRunResponse,
    RepoEvidenceBundle,
    RepoReportPayload,
    RepoSnapshot,
    RepoSubject,
)
from backend.services.base import BaseService


class RepoAnalysisService(BaseService[AbstractUnitOfWork]):
    async def create_run(
        self,
        *,
        user_id: uuid.UUID,
        repo_url: str,
        owner: str,
        repo: str,
        rubric_version: str,
    ) -> RepoAnalysisRun:
        return await self.uow.repo_analysis_repo.create_run(
            user_id=user_id,
            repo_url=repo_url,
            owner=owner,
            repo=repo,
            rubric_version=rubric_version,
        )

    async def set_task_id(
        self,
        *,
        run_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> RepoAnalysisRun | None:
        return await self.uow.repo_analysis_repo.set_task_id(
            run_id=run_id, task_id=task_id
        )

    async def get_run(self, run_id: uuid.UUID) -> RepoAnalysisRun | None:
        return await self.uow.repo_analysis_repo.get_run(run_id)

    async def get_user_run_response(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> RepoAnalysisRunResponse:
        run = await self.uow.repo_analysis_repo.get_run_for_user(
            run_id=run_id, user_id=user_id
        )
        if run is None:
            raise app_not_found(
                "分析任务不存在或无访问权限", code="REPO_ANALYSIS_NOT_FOUND"
            )
        return await self._build_response(run)

    async def mark_running(self, *, run_id: uuid.UUID) -> None:
        await self.uow.repo_analysis_repo.mark_running(run_id=run_id)

    async def mark_failed(self, *, run_id: uuid.UUID, error_message: str) -> None:
        await self.uow.repo_analysis_repo.mark_failed(
            run_id=run_id, error_message=error_message
        )

    async def save_success(
        self,
        *,
        run_id: uuid.UUID,
        subject: RepoSubject,
        snapshot: RepoSnapshot,
        evidence: RepoEvidenceBundle,
        report: RepoReportPayload,
    ) -> None:
        await self.uow.repo_analysis_repo.create_result(
            run_id=run_id,
            subject=subject.model_dump(mode="json"),
            snapshot=snapshot.model_dump(mode="json"),
            evidence=evidence.model_dump(mode="json"),
            structured_report=report.structured.model_dump(mode="json"),
            markdown_report=report.markdown,
            generated_by=report.generated_by,
        )
        await self.uow.repo_analysis_repo.mark_succeeded(run_id=run_id)

    async def _build_response(self, run: RepoAnalysisRun) -> RepoAnalysisRunResponse:
        result = await self.uow.repo_analysis_repo.get_result_for_run(run.id)
        response = RepoAnalysisRunResponse(run=_run_payload(run))
        if result is None:
            return response
        structured = ReadmeCredibilityAssessment.model_validate(
            {
                **result.structured_report,
                "caveat": result.structured_report.get("caveat") or README_ONLY_CAVEAT,
            }
        )
        return RepoAnalysisRunResponse(
            run=_run_payload(run),
            subject=RepoSubject.model_validate(result.subject),
            snapshot=RepoSnapshot.model_validate(result.snapshot),
            evidence=RepoEvidenceBundle.model_validate(result.evidence),
            report=RepoReportPayload(
                structured=structured,
                markdown=result.markdown_report,
                generated_by=result.generated_by,  # type: ignore[arg-type]
            ),
        )


def _run_payload(run: RepoAnalysisRun) -> RepoAnalysisRunPayload:
    status = (
        run.status.value if isinstance(run.status, RepoAnalysisStatus) else run.status
    )
    return RepoAnalysisRunPayload(
        id=run.id,
        status=status,
        repo_url=run.repo_url,
        owner=run.owner,
        repo=run.repo,
        task_id=run.task_id,
        rubric_version=run.rubric_version,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
