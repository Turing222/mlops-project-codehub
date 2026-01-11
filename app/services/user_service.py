import csv
import io
import logging

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.crud.user import get_existing_usernames

# 获取 logger 实例
logger = logging.getLogger(__name__)

async def process_user_import(user_maps: list[dict], session: AsyncSession):
    """
    业务逻辑层：负责解析文件并执行批量插入
    """
   #logger.info(f"Starting user import: filename={file.filename}")

    # 1. 提取所有待注册的用户名
    # 假设 user_maps 结构: [{"email": "a@a.com", "username": "u1"}, ...]
    incoming_usernames = [u["username"] for u in user_maps]
    
    # 2. 【关键步骤】调用 CRUD 进行预验证
    existing_names = await get_existing_usernames(session, incoming_usernames)
    
    # 3. 过滤数据（或者报错）
    # 方案 A：直接报错，告诉前端哪些名字重复了（推荐）
    if existing_names:
        raise ValueError(f"以下用户名已被占用，无法注册: {existing_names}")


    try:
        # 1. 读取文件内容
        '''
        content = await file.read()
        deck = io.StringIO(content.decode('utf-8'))
        reader = csv.DictReader(deck)
        
        user_maps = []
        BATCH_SIZE = 500

        for row in reader:
            # 基础格式校验
            if "email" not in row or "username" not in row:
                logger.warning(f"Invalid row format ignored: {row}")
                continue
            user_maps.append({"email": row["email"], "username": row["username"]})

        if not user_maps:
            logger.info("No valid user data found in file")
            return 0
        '''
        # 2. 执行批量 Upsert
        stmt = pg_insert(User)
        stmt = stmt.on_conflict_do_update(
            index_elements=['email'],
            set_={"username": stmt.excluded.username}
        )
        
        await session.execute(stmt, user_maps)
        await session.commit()
        
        logger.info(f"Successfully upserted {len(user_maps)} users")
        return len(user_maps)

    except UnicodeDecodeError as e:
        logger.error(f"File encoding error: {str(e)}")
        raise HTTPException(status_code=400, detail="Only UTF-8 CSV files are supported") from e
    
    except Exception as e:
        # 在这里记录堆栈信息，这对排查生产环境 bug 至关重要
        logger.exception(f"Unexpected error during user import: {str(e)}")
        await session.rollback()
        raise HTTPException(status_code=500, detail="Internal server error during import") from e