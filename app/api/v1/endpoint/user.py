from fastapi import APIRouter, Depends, File, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
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
    try:
        content = await file.read()
        raw_data = parse_file(file.filename, content)
    except Exception as e:
        raise FileParseException("发生未知文件导入异常") from e

    # 2. 数据字段映射 (Transform)
    # Excel 表头可能是 "用户名", "邮箱"，我们需要映射成数据库的 "username", "email"
    # 或者如果 Excel 已经是英文表头，这一步可以省略或做校验
    header_map = {
        "用户名": "username",
        "邮箱": "email",
        "username": "username",  # 兼容英文
        "email": "email",
    }

    cleaned_data = []
    for row in raw_data:
        new_row = {}
        for key, value in row.items():
            if key in header_map:
                # 这里可以加一些简单的数据清洗，比如 strip()
                new_row[header_map[key]] = str(value).strip() if value else None

        # 简单校验：关键字段不能为空
        if new_row.get("username") and new_row.get("email"):
            cleaned_data.append(new_row)

    if not cleaned_data:
        raise ValidationError("解析后没有有效数据")

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
