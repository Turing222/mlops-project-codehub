from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.dependencies import get_user_repo
from app.api.params import LimitParam, SkipParam, UsernameQuery
from app.core.database import get_session
from app.core.exceptions import (
    DatabaseOperationError,
    FileParseException,
    ServiceError,
    ValidationError,
)
from app.crud.user import create_user, get_users, upsert_users
from app.models.user import UserPublic
from app.repositories.user_repo import UserRepository
from app.services.user_service import process_user_import
from app.services.user_import_service import transform_and_validate
from app.utils.file_parser import parse_file

router = APIRouter()

'''
@router.get("/me")
def read_user_me(
    # 只需要这一行，FastAPI 就会自动执行鉴权和数据库注入
    current_user = Depends(deps.get_current_user)
):
    """获取当前登录用户信息"""
    return current_user

@router.post("/")
def create_user(
    db = Depends(deps.get_db),
    # 这里不需要鉴权，因为注册账号可能是公开的
):
    """创建新用户"""
    pass
'''


# 路由：查询用户
@router.get("/get_users", response_model=list[UserPublic])
async def read_users(
    repo: UserRepository = Depends(get_user_repo),
    username: UsernameQuery = None,  # 使用我们定义的类型，默认为 None
    skip: SkipParam = 0,
    limit: LimitParam = 10,
):
    users = await repo.get_users(username=username, skip=skip, limit=limit)
    return users


# 路由：初始化种子数据
@router.post("/init-data")
async def seed_data(session: AsyncSession = Depends(get_session)):
    mock_data = [
        {"username": "admin", "email": "admin@bank.com"},
        {"username": "dba_master", "email": "dba@bank.com"},
    ]
    await upsert_users(session, mock_data)
    return {"detail": "Seed data processed"}


# 接口：创建一个新用户
@router.post("/users/")
async def create_user_once(session: AsyncSession = Depends(get_session)):
    await create_user(
        session,
    )
    return {"status": "成功", "user": "admin"}


# 接口：通过文件上传批量插入客户
@router.post("/csv_upload")
async def csv_balk_insert_users(
    file: UploadFile = File(...),  # noqa: B008
    repo: UserRepository = Depends(get_user_repo),
):
    # 1. 读取文件内容到内存
    # 注意：如果文件巨大（几百MB），不能直接 read()，需要流式处理。
    # 但通常用户导入文件在 10MB 以内，直接读入内存没问题。

    content = await file.read()
    # raw_data = parse_file(file.filename, content) 修改为线程池处理减少同步函数造成的堵塞 run_in_threadpool用的是fastapi自己设置的默认的线程池
    raw_data = await run_in_threadpool(parse_file, file.filename, content)

    cleaned_data = await transform_and_validate(raw_data)
    # 3. 调用 Service 层入库 (Load)
    try:
        await process_user_import(cleaned_data, repo)
    except ValidationError:
        # 捕获 Service 层抛出的“用户名重复”等业务错误
        raise
    except DatabaseOperationError:
        # 捕获 Service 层抛出的“用户名重复”等业务错误
        raise
    except ServiceError:
        # 捕获 Service 层抛出的“用户名重复”等业务错误
        raise
    except Exception as e:
        # 捕获数据库未知错误
        raise ServiceError("服务器内部错误") from e

    return {"message": f"成功导入 {len(cleaned_data)} 条用户数据"}
