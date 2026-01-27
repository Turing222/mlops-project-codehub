import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.api.dependencies import get_user_service

# from app.api.params import LimitParam, SkipParam, UsernameQuery
from app.models.schemas.user import UserResponse, UserSearch, UserUpdate
from app.services.user_service import UserService
from app.utils.file_parser import parse_file

UserServiceDep = Annotated[UserService, Depends(get_user_service)]

router = APIRouter()


# 路由：查询用户
@router.get("", response_model=UserResponse)
async def read_user(
    # 使用 Depends() 将 Pydantic 模型转为 Query 参数解析
    search_params: Annotated[UserSearch, Depends()],
    service: UserServiceDep,
):
    """
    通过用户名或邮箱查询单个用户。
    DBA 视角：后端会根据参数存在与否，决定走 USERNAME 还是 EMAIL 的唯一索引。
    """
    if search_params.username:
        user = await service.get_by_username(search_params.username)
    elif search_params.email:
        user = await service.get_by_email(search_params.email)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either username or email",
        )

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    # 路径参数定位资源
    user_id: Annotated[uuid.UUID, Path(title="The ID of the user to update")],
    # 请求体提供更新数据
    user_in: UserUpdate,
    service: UserServiceDep,
):
    """
    局部更新用户信息。
    """
    updated_user = await service.user_update(user_id=user_id, update_schema=user_in)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user


# 接口：创建一个新用户
@router.patch("/users/")
async def update_user_(user_in: UserUpdate, service: UserServiceDep):
    return await service.user_update(user_in)


# 接口：通过文件上传批量插入客户
@router.post("/csv_upload")
async def csv_balk_insert_users(service: UserServiceDep, file: UploadFile = File(...)):  # noqa: B008
    # 1. 读取文件内容到内存
    # 注意：如果文件巨大（几百MB），不能直接 read()，需要流式处理。
    # 但通常用户导入文件在 10MB 以内，直接读入内存没问题。
    content = await file.read()
    # raw_data = parse_file(file.filename, content) 修改为线程池处理减少同步函数造成的堵塞 run_in_threadpool用的是fastapi自己设置的默认的线程池
    raw_data = await run_in_threadpool(parse_file, file.filename, content)
    # 字典映射与数据校验
    cleaned_data = await service.transform_and_validate(raw_data)
    # 3. 调用 Service 层入库 (Load)
    await service.import_users(cleaned_data)

    return {"message": f"成功导入 {len(cleaned_data)} 条用户数据"}
