import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile, status

from backend.api.dependencies import (
    get_current_active_user,
    get_knowledge_service,
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
from backend.tasks.knowledge_tasks import ingest_knowledge_file_task

router = APIRouter()


@router.post(
    "/bases/{kb_id}/upload",
    response_model=KnowledgeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_file(
    kb_id: uuid.UUID = Path(description="知识库 ID"),
    file: Annotated[UploadFile, File(...)] = ...,
    current_user: User = Depends(get_current_active_user),
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    task_service: TaskService = Depends(get_task_service),
):
    file_obj = await knowledge_service.save_upload_file(
        kb_id=kb_id,
        user_id=current_user.id,
        upload_file=file,
    )
    task = await task_service.create_kb_ingestion_task(
        kb_id=kb_id,
        file_id=file_obj.id,
        file_path=file_obj.file_path,
        filename=file_obj.filename,
        user_id=current_user.id,
    )

    try:
        await ingest_knowledge_file_task.kiq(str(file_obj.id), str(task.id))
    except Exception as exc:
        await task_service.mark_failed(task_id=task.id, error_log=f"任务投递失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"任务投递失败: {exc}",
        ) from exc

    return KnowledgeUploadResponse(
        task_id=task.id,
        file_id=file_obj.id,
        file_status=file_obj.status,
        task_status=task.status,
        file_path=file_obj.file_path,
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_status(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    task_service: TaskService = Depends(get_task_service),
):
    task = await task_service.get_by_id(task_id=task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    await task_service.ensure_user_access(task=task, user_id=current_user.id)
    return TaskResponse.model_validate(task)


@router.get("/files/{file_id}", response_model=KnowledgeFileResponse)
async def get_file_status(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    file_obj = await service.get_file(file_id=file_id)
    if not file_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    await service.ensure_kb_access(kb_id=file_obj.kb_id, user_id=current_user.id)
    return KnowledgeFileResponse.model_validate(file_obj)
