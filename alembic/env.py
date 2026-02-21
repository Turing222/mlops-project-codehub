import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# --- [重点 1] 解决路径问题 ---
# --- [修正 1] 确保根目录被加入路径 ---
# 获取 env.py 的绝对路径，再向上找两层，定位到根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# --- [重点 2] 引入你的逻辑 ---

from backend.core.config import settings  # noqa: E402
from backend.models.orm import Base  # noqa: E402

# 这里的 import User 非常重要，没它 metadata 就是空的
# from models.user import User

config = context.config

# 配置日志（保留默认）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置元数据


target_metadata = Base.metadata


# 设置buckup忽略函数
def include_object(object, name, type_, reflected, compare_to):
    # 如果是表，且名字包含 "backup"，则忽略
    if type_ == "table" and name and "backup" in name:
        return False
    return True


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """
    这是被 run_sync 调用的同步钩子。
    它接收一个被 SQLAlchemy 包装过的同步连接。
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    # 从配置节加载字典
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = str(settings.database_url)
    print(f"DEBUG: Connecting to {settings.database_url}")
    # 创建异步引擎
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        # 💡 桥接点：将同步的迁移函数跑在异步连接上
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    try:
        # 开启事件循环
        asyncio.run(run_migrations_online())
    except (KeyboardInterrupt, SystemExit):
        pass
