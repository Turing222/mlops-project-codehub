import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile, status

from backend.api.dependencies import (
    get_audit_service,
    get_current_active_user,
    get_current_superuser,
    get_permission_service,
    get_user_import_service,
    get_user_service,
)
from backend.models.orm.user import User
from backend.models.schemas.user_schema import (
    UserCreate,
    UserImportResponse,
    UserResponse,
    UserSearch,
    UserUpdate,
)
from backend.services.audit_service import AuditAction, AuditService, capture_audit
from backend.services.permission_service import PermissionService
from backend.services.user_import_service import UserImportService
from backend.services.user_service import UserService

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
SuperUser = Annotated[User, Depends(get_current_superuser)]
UpFile = Annotated[UploadFile, File()]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
UserImportServiceDep = Annotated[UserImportService, Depends(get_user_import_service)]


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: CurrentUser,
    permission_service: PermissionService = Depends(get_permission_service),
):
    user_resp_data = UserResponse.model_validate(current_user)

    # 复杂的、变动的、关联的字段，手动覆盖
    # user_resp_data.org_name = current_user.organization.name if current_user.organization else "独立用户"

    return user_resp_data


# 路由：查询用户
@router.get("", response_model=UserResponse)
async def read_user(
    search_params: Annotated[UserSearch, Depends()],
    _: SuperUser,
    user_service: UserServiceDep,
    permission_service: PermissionService = Depends(get_permission_service),
):
    """
    通过用户名或邮箱查询单个用户。
    DBA 视角：后端会根据参数存在与否，决定走 USERNAME 还是 EMAIL 的唯一索引。
    """
    async with user_service.uow:
        if search_params.username:
            user = await user_service.get_by_username(search_params.username)
        elif search_params.email:
            user = await user_service.get_by_email(search_params.email)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide either username or email",
            )

        if not user:
            raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    # 路径参数定位资源
    user_id: Annotated[uuid.UUID, Path(title="The ID of the user to update")],
    # 请求体提供更新数据
    user_in: UserUpdate,
    _: SuperUser,
    user_service: UserServiceDep,
    permission_service: PermissionService = Depends(get_permission_service),
    audit_service: AuditService = Depends(get_audit_service),
):
    """
    局部更新用户信息。
    """
    async with capture_audit(
        audit_service,
        action=AuditAction.USER_UPDATE,
        actor_user_id=_.id,
        resource_type="user",
        resource_id=user_id,
        metadata={"updated_fields": list(user_in.model_fields_set)},
    ):
        async with user_service.uow:
            updated_user = await user_service.user_update(user_id=user_id, user_in=user_in)
            if not updated_user:
                raise HTTPException(status_code=404, detail="User not found")
        return UserResponse.model_validate(updated_user)


# 接口：创建一个新用户
@router.post("", response_model=UserResponse)
async def create_user(
    user_in: UserCreate,
    _: SuperUser,
    user_service: UserServiceDep,
    permission_service: PermissionService = Depends(get_permission_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> UserResponse:
    async with capture_audit(
        audit_service,
        action=AuditAction.USER_CREATE,
        actor_user_id=_.id,
        resource_type="user",
        metadata={"username": user_in.username, "email": user_in.email},
    ) as audit:
        async with user_service.uow:
            user = await user_service.user_register_with_personal_workspace(user_in)
            if not user:
                raise HTTPException(status_code=400, detail="User creation failed")
            audit.set_resource(resource_id=user.id)
            return UserResponse.model_validate(user)


# 接口：通过文件上传批量插入客户
@router.post("/csv_upload", response_model=UserImportResponse)
async def csv_balk_insert_users(
    file: UpFile,
    _: SuperUser,
    import_service: UserImportServiceDep,
    permission_service: PermissionService = Depends(get_permission_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> UserImportResponse:
    async with capture_audit(
        audit_service,
        action=AuditAction.USER_IMPORT_CSV,
        actor_user_id=_.id,
        resource_type="user",
        metadata={"filename": getattr(file, "filename", None)},
    ) as audit:
        async with import_service.uow:
            result = await import_service.import_from_upload(file)
            audit.add_metadata(
                total_rows=result.total_rows,
                imported_rows=result.imported_rows,
            )
            return result
