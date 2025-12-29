from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# 这里的数据库地址会读取你的 .env 或默认值
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/my_db")

engine = create_engine(SQLALCHEMY_DATABASE_URL)
# SessionLocal 是一个类，还不是真正的连接
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()