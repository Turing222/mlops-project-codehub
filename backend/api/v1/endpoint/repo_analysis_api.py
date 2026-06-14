"""Repo analysis API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import (
    get_current_active_user,
    get_repo_analysis_service,
    get_repo_analysis_submit_workflow,
)
from backend.application.repo_analysis.submit_workflow import RepoAnalysisSubmitWorkflow
from backend.models.orm.user import User
from backend.models.schemas.repo_analysis_schema import (
    RepoAnalysisRunResponse,
    RepoAnalysisSubmitRequest,
    RepoAnalysisSubmitResponse,
)
from backend.services.repo_analysis_service import RepoAnalysisService

router = APIRouter()
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
RepoAnalysisWorkflowDep = Annotated[
    RepoAnalysisSubmitWorkflow, Depends(get_repo_analysis_submit_workflow)
]
RepoAnalysisServiceDep = Annotated[
    RepoAnalysisService, Depends(get_repo_analysis_service)
]


@router.post(
    "/readme-check",
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_readme_check(
    payload: RepoAnalysisSubmitRequest,
    current_user: CurrentUserDep,
    workflow: RepoAnalysisWorkflowDep,
) -> RepoAnalysisSubmitResponse:
    return await workflow.submit(
        repo_url=payload.repo_url,
        user_id=current_user.id,
    )


@router.get("/runs/{run_id}")
async def get_repo_analysis_run(
    run_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: RepoAnalysisServiceDep,
) -> RepoAnalysisRunResponse:
    async with service.read():
        return await service.get_user_run_response(
            run_id=run_id,
            user_id=current_user.id,
        )
