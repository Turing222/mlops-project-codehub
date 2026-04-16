import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from backend.api.dependencies import (
    get_current_active_user,
    get_knowledge_service,
    get_knowledge_upload_workflow,
    get_task_service,
)
from backend.models.orm.user import User
from backend.models.schemas.knowledge_schema import (
    KnowledgeFileResponse,
    KnowledgeUploadResponse,
)
from backend.models.schemas.task_schema import TaskResponse
from backend.services.knowledge_service import KnowledgeService
from backend.services.task_service import TaskService
from backend.workflow.knowledge_upload_workflow import KnowledgeUploadWorkflow

router = APIRouter()
UpFile = Annotated[UploadFile, File()]
CurrentUser = Annotated[User, Depends(get_current_active_user)]
KnowledgeUploadWorkflowDep = Annotated[
    KnowledgeUploadWorkflow, Depends(get_knowledge_upload_workflow)
]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]


@router.post(
    "/bases/{kb_id}/upload",
    response_model=KnowledgeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_file(
    kb_id: uuid.UUID,
    file: UpFile,
    current_user: CurrentUser,
    upload_workflow: KnowledgeUploadWorkflowDep,
) -> KnowledgeUploadResponse:
    return await upload_workflow.submit_ingestion(
        kb_id=kb_id,
        user_id=current_user.id,
        upload_file=file,
    )


@router.post(
    "/bases/{kb_id}/upload-stream",
    response_model=KnowledgeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_file_stream(
    kb_id: uuid.UUID,
    file: UpFile,
    current_user: CurrentUser,
    upload_workflow: KnowledgeUploadWorkflowDep,
) -> KnowledgeUploadResponse:
    return await upload_workflow.submit_stream_ingestion(
        kb_id=kb_id,
        user_id=current_user.id,
        upload_file=file,
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_status(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    task_service: TaskServiceDep,
) -> TaskResponse:
    async with task_service.uow:
        task = await task_service.get_by_id(task_id=task_id)
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

        await task_service.ensure_user_access(task=task, user_id=current_user.id)
    return TaskResponse.model_validate(task)


@router.get("/files/{file_id}", response_model=KnowledgeFileResponse)
async def get_file_status(
    file_id: uuid.UUID,
    current_user: CurrentUser,
    service: KnowledgeServiceDep,
) -> KnowledgeFileResponse:
    async with service.uow:
        file_obj = await service.get_file(file_id=file_id)
        if not file_obj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

        await service.ensure_kb_access(kb_id=file_obj.kb_id, user_id=current_user.id)
    return KnowledgeFileResponse.model_validate(file_obj)
