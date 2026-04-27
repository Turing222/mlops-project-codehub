from fastapi import Depends

from backend.api.deps.uow import get_uow
from backend.domain.interfaces import AbstractUnitOfWork
from backend.services.permission_service import PermissionService


def get_permission_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> PermissionService:
    return PermissionService(uow=uow)
