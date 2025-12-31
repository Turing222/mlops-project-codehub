#串联所有程序
from fastapi import FastAPI, Depends
from sqlmodel import Session, select
from database import engine  # 假设你把 create_engine 放在了 database.py
from models import User      # 假设你把 User 类放在了 models.py

app = FastAPI()

# 获取数据库会话的工具函数
def get_session():
    with Session(engine) as session:
        yield session

@app.get("/")
def read_root():
    return {"message": "AI Mentor 数据库已就绪！"}

# 接口：创建一个新用户
@app.post("/users/")
def create_user(username: str, email: str, session: Session = Depends(get_session)):
    db_user = User(username=username, email=email)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return {"status": "成功", "user": db_user}

# 接口：查看所有用户
@app.get("/users/")
def read_users(session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()
    return users