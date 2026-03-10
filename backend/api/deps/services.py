from fastapi import Depends

from backend.api.deps.uow import get_uow
from backend.core.config import settings
from backend.domain.interfaces import AbstractUnitOfWork
from backend.services.knowledge_service import KnowledgeService
from backend.services.task_service import TaskService


def get_knowledge_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> KnowledgeService:
    return KnowledgeService(
        uow=uow,
        storage_root=settings.KNOWLEDGE_STORAGE_ROOT,
    )


def get_task_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> TaskService:
    return TaskService(uow=uow)

