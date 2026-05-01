from functools import lru_cache

from fastapi import Depends

from backend.api.deps.uow import get_uow
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.services.knowledge_service import KnowledgeService
from backend.services.object_storage import ObjectStorage, create_object_storage
from backend.services.permission_service import PermissionService
from backend.services.session_query_service import SessionQueryService
from backend.services.task_service import TaskService
from backend.services.user_import_service import UserImportService
from backend.services.user_service import UserService
from backend.services.workspace_service import WorkspaceService


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """进程级单例：S3 client 有连接池，每次请求重建开销高。

    测试时可通过 get_object_storage.cache_clear() + app.dependency_overrides 重置。
    """
    return create_object_storage(settings)


def get_knowledge_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
    storage: ObjectStorage = Depends(get_object_storage),
) -> KnowledgeService:
    return KnowledgeService(
        uow=uow,
        storage=storage,
        max_upload_size_mb=settings.KNOWLEDGE_MAX_UPLOAD_SIZE_MB,
        permission_service=PermissionService(uow),
    )


def get_task_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> TaskService:
    return TaskService(uow=uow)


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


def get_workspace_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> WorkspaceService:
    return WorkspaceService(uow=uow)
