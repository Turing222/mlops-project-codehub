from fastapi import Depends

from backend.api.deps.uow import get_uow
from backend.core.config import settings
from backend.domain.interfaces import AbstractUnitOfWork
from backend.services.knowledge_service import KnowledgeService
from backend.services.knowledge_upload_service import KnowledgeUploadService
from backend.services.session_query_service import SessionQueryService
from backend.services.task_service import TaskService
from backend.services.user_import_service import UserImportService
from backend.services.user_service import UserService


def get_knowledge_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> KnowledgeService:
    return KnowledgeService(
        uow=uow,
        storage_root=settings.KNOWLEDGE_STORAGE_ROOT,
        max_upload_size_mb=settings.KNOWLEDGE_MAX_UPLOAD_SIZE_MB,
    )


def get_task_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> TaskService:
    return TaskService(uow=uow)


def get_knowledge_upload_service(
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    task_service: TaskService = Depends(get_task_service),
) -> KnowledgeUploadService:
    return KnowledgeUploadService(
        knowledge_service=knowledge_service,
        task_service=task_service,
    )


def get_session_query_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> SessionQueryService:
    return SessionQueryService(uow=uow)


def get_user_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> UserService:
    return UserService(uow=uow)


def get_user_import_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> UserImportService:
    return UserImportService(uow=uow)
