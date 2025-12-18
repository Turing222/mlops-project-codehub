#目录结构
obsidian-mentor-ai/
├── pyproject.toml              # 依赖管理 (uv)
├── .env                        # 环境变量 (绝不提交到 Git)
├── docker-compose.yml          # 容器编排
├── alembic.ini                 # 数据库迁移配置 (生产环境必备)
│
└── app/                        # 核心代码库
    ├── __init__.py
    ├── main.py                 # 【入口】程序的启动点，负责串联所有模块
    │
    ├── core/                   # 【配置核心】存放全局配置
    │   ├── config.py           # Pydantic Settings (读取 .env)
    │   ├── database.py         # 数据库连接池 session maker
    │   └── exceptions.py       # 自定义异常处理
    │
    ├── models/                 # 【数据模型】(SQLAlchemy Table 定义)
    │   ├── base.py
    │   ├── user.py             # 用户表 (fastapi-users 需要)
    │   └── knowledge.py        # 笔记元数据表/向量表
    │
    ├── schemas/                # 【数据验证】(Pydantic Models)
    │   ├── user.py             # 用户注册/登录的校验模型
    │   └── chat.py             # 聊天输入输出的校验模型
    │
    ├── api/                    # 【接口层】(FastAPI Routers)
    │   ├── deps.py             # 依赖注入 (Dependency Injection)
    │   ├── v1/
    │   │   ├── router.py       # 总路由
    │   │   ├── auth.py         # 登录注册接口
    │   │   └── ingestion.py    # 触发笔记同步的接口
    │
    ├── services/               # 【业务逻辑层】(最核心的大脑)
    │   ├── rag_service.py      # LlamaIndex 的封装 (检索、生成)
    │   ├── ingestion_service.py# 读取 Obsidian、清洗、切分的逻辑
    │   └── user_service.py     # 用户管理逻辑
    │
    └── ui/                     # 【前端层】(Chainlit)
        └── chainlit_app.py     # Chainlit 的入口脚本 (UI 逻辑)

#技术栈
Chainlit: 负责 UI 和 交互逻辑（自带 X-Ray 步骤展示）。

langchain（备选LlamaIndex）: 负责连接粘连各个位置 和 RAG 逻辑

LangFuse radis：模型评估 
Prometheus ： 系统监控
Grafana：整个一个仪表盘方面查看

LLM :（vLLM/llama.cpp）本地模型 联网模型选择 gemini api


fastapi：微服务框架

fastapi-user:负责权限管理

mysql：普通数据库

PostgreSQL (pgvector): 向量数据库。

Docker Compose: 一键编排。 

后续添加redis 缓存 和 k8s 多服务器部署

