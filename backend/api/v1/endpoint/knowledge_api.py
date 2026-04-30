import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from backend.api.dependencies import (
    get_audit_service,
    get_current_active_user,
    get_knowledge_service,
    get_knowledge_upload_workflow,
    get_permission_service,
    get_task_service,
)
from backend.core.exceptions import app_not_found
from backend.models.orm.user import User
from backend.models.schemas.knowledge_schema import (
    KnowledgeFileResponse,
    KnowledgeUploadResponse,
)
from backend.models.schemas.task_schema import TaskResponse
from backend.services.audit_service import AuditAction, AuditService, capture_audit
from backend.services.knowledge_service import KnowledgeService
from backend.services.permission_service import PermissionService
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
    "/default/upload",
    response_model=KnowledgeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_file_to_default_kb(
    file: UpFile,
    current_user: CurrentUser,
    upload_workflow: KnowledgeUploadWorkflowDep,
    audit_service: AuditService = Depends(get_audit_service),
) -> KnowledgeUploadResponse:
    async with capture_audit(
        audit_service,
        action=AuditAction.FILE_UPLOAD_SUBMIT,
        actor_user_id=current_user.id,
        resource_type="file",
        metadata={
            "filename": getattr(file, "filename", None),
            "default_kb": True,
        },
    ) as audit:
        result = await upload_workflow.submit(
            user_id=current_user.id,
            upload_file=file,
        )
        audit.set_resource(resource_id=result.file_id)
        audit.add_metadata(
            task_id=str(result.task_id),
            kb_id=str(result.kb_id) if result.kb_id else None,
        )
        return result


# TODO: 未来如需真正的流式上传（Request.stream() 绕过 UploadFile 缓冲），
#       可新增 /upload-stream 端点并在 workflow.submit 中传入 stream 参数。


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
    permission_service: PermissionService = Depends(get_permission_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> KnowledgeUploadResponse:
    async with capture_audit(
        audit_service,
        action=AuditAction.FILE_UPLOAD_SUBMIT,
        actor_user_id=current_user.id,
        resource_type="file",
        metadata={"kb_id": str(kb_id), "filename": getattr(file, "filename", None)},
    ) as audit:
        result = await upload_workflow.submit(
            kb_id=kb_id,
            user_id=current_user.id,
            upload_file=file,
        )
        audit.set_resource(resource_id=result.file_id)
        audit.add_metadata(task_id=str(result.task_id))
        return result


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_status(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    task_service: TaskServiceDep,
    permission_service: PermissionService = Depends(get_permission_service),
) -> TaskResponse:
    async with task_service.uow:
        task = await task_service.get_by_id(task_id=task_id)
        if not task:
            raise app_not_found("任务不存在", code="TASK_NOT_FOUND")

        await task_service.ensure_user_access(task=task, user_id=current_user.id)
    return TaskResponse.model_validate(task)


@router.get("/files/{file_id}", response_model=KnowledgeFileResponse)
async def get_file_status(
    file_id: uuid.UUID,
    current_user: CurrentUser,
    service: KnowledgeServiceDep,
    permission_service: PermissionService = Depends(get_permission_service),
) -> KnowledgeFileResponse:
    async with service.uow:
        file_obj = await service.get_file(file_id=file_id)
        if not file_obj:
            raise app_not_found("文件不存在", code="KNOWLEDGE_FILE_NOT_FOUND")

        await service.ensure_kb_access(kb_id=file_obj.kb_id, user_id=current_user.id)
    return KnowledgeFileResponse.model_validate(file_obj)
