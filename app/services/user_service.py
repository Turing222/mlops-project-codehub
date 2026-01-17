import logging

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import settings
from app.core.exceptions import DatabaseOperationError, ServiceError, ValidationError
from app.repositories.user_repo import UserRepository

# 获取 logger 实例
logger = logging.getLogger(__name__)


async def process_user_import(user_maps: list[dict], repo: UserRepository):
    """
    业务逻辑层：负责解析文件并执行批量插入
    """
    # logger.info(f"Starting user import: filename={file.filename}")

    # 1. 提取所有待注册的用户名
    # 假设 user_maps 结构: [{"email": "a@a.com", "username": "u1"}, ...]
    incoming_usernames = [u["username"] for u in user_maps]

    if not user_maps:
        logger.info("No valid user data found in file")
        raise ValidationError("有效客户为0")

    size = settings.BATCH_SIZE
    batches = [user_maps[i : i + size] for i in range(0, len(user_maps), size)]
    total_batches = len(batches)
    total_records = sum(len(b) for b in batches)

    try:
        # 2. 【关键步骤】调用 CRUD 进行预验证
        existing_names = await repo.get_existing_usernames(incoming_usernames)

        # 3. 过滤数据（或者报错）
        # 方案 A：直接报错，告诉前端哪些名字重复了（推荐）
        if existing_names:
            raise ValidationError(f"以下用户名已被占用，无法注册: {existing_names}")

        for i, batch in enumerate(batches, 1):
            if not batch:
                continue
            # --- 你的核心逻辑 ---
            await repo.bulk_upsert(batch)
            # 记录进度（debug 级别，防止生产环境日志刷屏）
            logger.debug(f"批次 [{i}/{total_batches}] 处理完成，本批 {len(batch)} 条")

        # 退出 async with 后自动 commit
        logger.info(f"批量处理成功,事务已提交,成功提交 {total_records} 用户")

    except UnicodeDecodeError as e:
        # logger.error(f"文件编码异常: {str(e)}")
        raise ValidationError("Only UTF-8 CSV files are supported") from e

    except IntegrityError as e:
        # 捕获完整性错误（比如违反了其他唯一约束，且没在 on_conflict 处理）
        # logger.error(f"数据完整性错误: {str(e)}")
        # 抛出自定义异常，并不让上层看到原始 SQL 报错
        raise DatabaseOperationError("数据违反了唯一性约束或其他限制") from e

    except SQLAlchemyError as e:
        # 捕获其他数据库错误（如连接断开、SQL 语法错误等）
        # logger.error(f"数据库底层异常: {str(e)}")
        # 使用 'from e' 保留原始异常链，方便 traceback 追踪
        raise DatabaseOperationError("数据库操作执行失败") from e

    except Exception as e:
        # 在这里记录堆栈信息，这对排查生产环境 bug 至关重要
        # logger.exception(f"Unexpected error during user import: {str(e)}")
        # await session.rollback()
        raise ServiceError("Internal server error during import") from e
