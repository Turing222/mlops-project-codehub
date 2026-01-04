from typing import Optional
from sqlmodel import Field, SQLModel, create_engine
import os

# 1. 定义模型
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True)
    email: str = Field(unique=True)

# 2. 构建连接字符串（这里我们直接从你的逻辑中提取）
# 注意：如果你在 WSL 里跑代码连 Docker，用 localhost 即可
DATABASE_URL = "postgresql://admin:securepassword123@localhost:5432/mentor_db"

engine = create_engine(DATABASE_URL)

def create_db_and_tables():
    print("正在连接数据库并同步表结构...")
    SQLModel.metadata.create_all(engine)
    print("成功！现在去 DBeaver 里刷新看看。")

if __name__ == "__main__":
    create_db_and_tables()