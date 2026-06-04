# Legacy Backend README

> 这是保留的旧版根 README，主要反映仓库在“后端主视角”阶段的说明内容。
> 
> 当前建议优先从仓库级入口 [../README.md](../README.md) 开始阅读；本文件暂时保留，不删除，供历史参考与补充查阅。

# Dewflow AI Backend

基于 FastAPI + PostgreSQL(pgvector) + Redis + TaskIQ 的异步 AI 服务后端，采用分层架构与 Ports & Adapters（六边形架构）模式。

## 1. 架构概览

```text
API Layer (api/)       → 路由 + FastAPI Depends 依赖注入
Workflow Layer          → 业务流程编排（幂等、事务边界、SSE 流消费）
Service Layer           → 领域业务逻辑
Repository Layer        → 数据访问抽象
Infrastructure (infra/) → DB / Redis / TaskIQ 适配器
ORM Models              → SQLAlchemy 表定义
```

核心抽象定义在 `backend/contracts/interfaces.py`：`AbstractUnitOfWork`、`AbstractLLMService`、`AbstractRAGService`、`AbstractRAGEmbedder`。

### 核心能力

- **用户认证与权限**：注册、登录（JWT + bcrypt）、超级管理员、工作区 RBAC
- **对话系统**：SSE 流式问答（`/chat/query_stream`）、非流式问答（`/chat/query_sent`）、会话管理、`client_request_id` 幂等控制、Token 配额
- **知识库 RAG**：文件上传 → TaskIQ 异步解析/切片/向量化入库 → 向量/全文/混合检索 → RAG 增强回答
- **工作区管理**：CRUD + 成员管理 + OWNER/ADMIN/MEMBER 角色 + 权限矩阵
- **审计日志**：操作审计记录，支持按资源/用户/时间范围查询
- **可观测性**：OpenTelemetry 全链路追踪、Langfuse LLM 可观测、JSON 结构化日志、Prometheus `/metrics`
- **稳定性**：Redis Lua 滑动窗口限流、LLM 断路器、进程内并发控制

## 2. 技术栈

- **Web**: FastAPI + Uvicorn + Gunicorn（生产）
- **ORM**: SQLAlchemy 2.0 (async) + Alembic
- **DB**: PostgreSQL 17 + pgvector（HNSW 索引）
- **Cache / Queue**: Redis（应用缓存 + TaskIQ broker）
- **Async Task**: TaskIQ + taskiq-redis
- **LLM Provider**: OpenAI-compatible / DeepSeek / Gemini（Pydantic AI）/ Mock
- **Embedding**: Google Gemini / OpenAI-compatible
- **Parsing**: pypdfium2（PDF）、纯文本直接切分
- **Observability**: OpenTelemetry (OTLP) + Langfuse + JSON structured logging
- **Auth**: JWT (HS256) + bcrypt (pwdlib)

## 3. 项目目录

```text
backend/
├── main.py                      # FastAPI 入口（lifespan、路由、中间件注册）
├── api/
│   ├── deps/                    # 依赖注入（uow / auth / ai / services / workflows / permissions）
│   └── v1/
│       ├── api.py               # 路由聚合
│       └── endpoint/            # 各领域 HTTP 端点
├── ai/
│   ├── core/                    # Prompt 管理、token 计数、chat context 构建
│   └── providers/
│       ├── llm/                 # LLM 服务（stream / generate） + 断路器
│       └── embedding/           # RAG embedding 工厂
├── config/                      # 应用配置加载（Pydantic Settings + YAML）
├── contracts/                   # 抽象接口（Ports）
├── core/                        # 异常处理、JWT 安全、断路器、并发控制
├── infra/                       # 基础设施适配器（database、redis、task_broker）
├── middleware/                   # ASGI 中间件（tracing、rate_limit）
├── models/
│   ├── orm/                     # SQLAlchemy 模型（user / chat / knowledge / chunk / task / access）
│   └── schemas/                 # Pydantic 请求/响应 DTO
├── observability/               # 日志、OTel 遥测、trace 工具
├── repositories/                # 仓储层（user / chat / knowledge / task / access）
├── services/                    # 领域服务
├── tasks/                       # TaskIQ worker 任务（llm / knowledge）
├── workflow/                    # 业务编排（chat_stream / chat_nonstream / knowledge_upload / knowledge_rag）
└── utils/                       # 文件解析、校验工具

configs/                         # 非敏感 YAML 配置
├── app/                         # base / local / prod / test 环境覆盖
├── llm/                         # models.yaml（provider profile）+ prompts.yaml（Jinja2 模板）
└── access/                      # permissions.yaml（角色→权限映射）

tests/
├── unit/                        # 单元测试
├── integration/                 # 集成测试
├── smoke/                       # HTTP 冒烟测试
└── performance/                 # Locust 人工探索压测

perf/                            # 标准化 HTTP 性能压测、profiles、reports
```

## 4. 快速开始

### 4.1 环境要求

- Python 3.12
- PostgreSQL 17（pgvector 扩展）
- Redis
- `uv`（包管理）

### 4.2 安装与迁移

```bash
uv sync
uv run alembic upgrade head
```

### 4.3 环境变量

**必填**（无默认值，缺一不可启动）：

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | JWT 签名密钥 |

**数据库**（不设 `DATABASE_URL` 时按以下拼装）：

| 变量 | 默认值 |
|------|--------|
| `POSTGRES_USER` | `postgres` |
| `POSTGRES_PASSWORD` | — |
| `POSTGRES_SERVER` | `localhost` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_DB` | `dewflow` |
| `POSTGRES_POOL_SIZE` | `10` |
| `POSTGRES_MAX_OVERFLOW` | `20` |
| `POSTGRES_SSL_MODE` | —（可选 `disable` / `require`） |

**Redis**（不设 `REDIS_URL` / `TASKIQ_REDIS_URL` 时按以下拼装，TaskIQ 默认使用 DB 1）：

| 变量 | 默认值 |
|------|--------|
| `REDIS_HOST` | `localhost` |
| `REDIS_PORT` | `6379` |
| `REDIS_PASSWORD` | — |

**LLM**：

| 变量 | 默认值 |
|------|--------|
| `LLM_PROVIDER` | `mock`（可选 `openai-compatible` / `deepseek` / `gemini`） |
| `LLM_API_KEY` | — |
| `LLM_BASE_URL` | `https://api.openai.com/v1` |
| `LLM_MAX_CONCURRENCY` | `5` |
| `LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `5` |
| `LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `30` |

Provider 密钥：`OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` / `DEEPSEEK_API_KEY`

**RAG / Embedding**：

| 变量 | 默认值 |
|------|--------|
| `RAG_EMBED_PROVIDER` | `google` |
| `RAG_EMBED_DIM` | `768` |
| `RAG_TOP_K` | `4` |
| `KNOWLEDGE_CHUNK_SIZE` | `800` |
| `KNOWLEDGE_MAX_UPLOAD_SIZE_MB` | `20` |

**存储**：

| 变量 | 默认值 |
|------|--------|
| `STORAGE_BACKEND` | `local`（可选 `s3`） |
| `LOCAL_STORAGE_ROOT` | `.files/knowledge_files` |
| `S3_BUCKET` / `S3_REGION` / `S3_ENDPOINT_URL` | — |

**限流**：

| 变量 | 默认值 |
|------|--------|
| `AUTH_REGISTER_RATE_LIMIT_TIMES` | `10` |
| `AUTH_REGISTER_RATE_LIMIT_SECONDS` | `60` |
| `AUTH_LOGIN_RATE_LIMIT_TIMES` | `20` |
| `AUTH_LOGIN_RATE_LIMIT_SECONDS` | `60` |
| `BUSINESS_RATE_LIMIT_TIMES` | `100` |
| `BUSINESS_RATE_LIMIT_SECONDS` | `60` |
| `CHAT_RATE_LIMIT_TIMES` | `10` |
| `CHAT_RATE_LIMIT_SECONDS` | `60` |
| `CHAT_STREAM_FIRST_MESSAGE_TIMEOUT_SECONDS` | `30` |
| `CHAT_STREAM_MESSAGE_TIMEOUT_SECONDS` | `10` |

**可观测性**（可选）：

| 变量 | 说明 |
|------|------|
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse LLM 观测 |
| `LANGFUSE_BASE_URL` | 默认 `https://us.cloud.langfuse.com` |
| `ENABLE_OTEL_TRACES` | 开启 DB tracing（`true` / `1`） |

说明：
- 支持 `.env` + `.env.{APP_ENV}` + `configs/app/{APP_ENV}.yaml` 三层配置覆盖。
- Docker secrets 支持：设置 `*_FILE` 环境变量可从文件读取敏感值。
- 应用启动时会校验 `LLM_PROVIDER != mock` 时 `LLM_API_KEY` 非空。

### 4.4 YAML 配置

`configs/` 目录存放非敏感配置，可通过 `CONFIG_DIR` 环境变量指定路径：

- `configs/app/base.yaml` + `{APP_ENV}.yaml`：应用级覆盖配置。
- `configs/llm/models.yaml`：LLM / embedding provider profile（模型名、base URL、API key 环境变量名、维度）。
- `configs/llm/prompts.yaml`：Jinja2 system prompt、RAG prompt、summary prompt。支持 Langfuse 远程同步缓存，详见下文。
- `configs/access/permissions.yaml`：工作区角色→权限映射。

Langfuse prompt 缓存：
```bash
uv run python scripts/prompts/pull_from_langfuse.py --label production
```
拉取后写入 `.cache/langfuse/prompts.production.yaml`（不进 Git）。API 优先读缓存，TTL 到期自动重载；缓存缺失则降级到 `configs/llm/prompts.yaml`。

## 5. 启动服务

### 5.1 API

```bash
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5.2 TaskIQ Worker（必须）

```bash
uv run taskiq worker backend.infra.task_broker:broker backend.worker.tasks.llm_tasks backend.worker.tasks.knowledge_tasks backend.worker.tasks.repo_analysis_tasks --workers 2
```

### 5.3 Docker Compose

```bash
# 仅数据库 + Redis（开发）
docker compose -f docker-compose.db.yml up -d

# 全栈（生产）
docker compose -f deploy/docker-compose.yml up -d
```

## 6. API 清单

基准前缀：本地直连 `/v1`，反向代理后 `/api/v1`。

### 6.1 Auth

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 注册 |
| POST | `/auth/login` | 登录（返回 Bearer Token） |

### 6.2 Users

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/users/me` | 当前用户信息 |
| GET | `/users` | 查询单用户（需 superuser） |
| PATCH | `/users/{user_id}` | 更新用户（需 superuser） |
| POST | `/users` | 创建用户（需 superuser） |
| POST | `/users/csv_upload` | CSV/XLSX 批量导入（需 superuser） |

### 6.3 Chat

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat/query_sent` | 非流式问答 |
| POST | `/chat/query_stream` | SSE 流式问答 |
| GET | `/chat/sessions` | 会话列表 |
| GET | `/chat/sessions/{session_id}` | 会话详情（含历史消息） |

`query_stream` SSE 事件：
- `meta` — 携带 `session_id`、`session_title`、`message_id`
- `chunk` — 流式文本片段
- `error` — 错误消息
- `[DONE]` — 流结束

### 6.4 Knowledge

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/knowledge/bases` | 创建知识库 |
| POST | `/knowledge/bases/{kb_id}/upload` | 上传文件触发异步入库 |
| GET | `/knowledge/tasks/{task_id}` | 查询任务状态 |
| GET | `/knowledge/files/{file_id}` | 查询文件状态 |

文件状态流转：`uploaded` → `parsing` → `chunking` → `ready` / `failed`
任务状态流转：`pending` → `processing` → `completed` / `failed`
支持格式：`.txt` `.md` `.csv` `.json` `.yaml` `.py` `.pdf` 等。

### 6.5 Workspaces

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/workspaces` | 创建工作区 |
| GET | `/workspaces` | 工作区列表 |
| GET | `/workspaces/{workspace_id}` | 工作区详情 |
| PATCH | `/workspaces/{workspace_id}` | 更新工作区 |
| DELETE | `/workspaces/{workspace_id}` | 软删除工作区 |
| GET | `/workspaces/{workspace_id}/members` | 成员列表 |
| POST | `/workspaces/{workspace_id}/members` | 添加成员 |
| PATCH | `/workspaces/{workspace_id}/members/{user_id}` | 更新成员角色 |
| DELETE | `/workspaces/{workspace_id}/members/{user_id}` | 移除成员 |

角色：`OWNER` / `ADMIN` / `MEMBER`，最后一位 OWNER 不可降级或移除。

### 6.6 Permissions & Audit

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/permissions/policy` | 查看权限策略配置 |
| GET | `/audit/events` | 查询审计事件（支持按资源/用户/时间筛选） |

### 6.7 Health & Debug

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health_check/live` | 存活探针 |
| GET | `/health_check/db_ready` | 数据库就绪探针 |
| GET | `/metrics` | Prometheus 指标（OTLP 推送） |
| GET | `/debug-request` | 请求调试信息 |

## 7. 数据模型

| 表 | 说明 |
|------|------|
| `users` | 用户、权限、Token 配额 |
| `chat_sessions` | 对话会话 |
| `chat_messages` | 消息（状态、token 统计、search_context、幂等 id） |
| `knowledge_bases` | 知识库 |
| `knowledge_files` | 知识文件 |
| `document_chunks` | 文档切片（pgvector embedding + HNSW） |
| `task_jobs` | 异步任务 |
| `workspaces` | 工作区 |
| `user_workspace_roles` | 用户→工作区角色关联 |
| `audit_events` | 审计日志 |

## 8. 观测与运维

- **日志**：JSON 结构化输出（`orjson`），统一携带 `request_id`。
- **追踪**：
  - HTTP 层注入 `X-Request-ID`（入站复用，出站透传）、`X-Trace-ID`、`X-Process-Time`
  - OpenTelemetry OTLP 导出（DB SQL tracing 需配置 `ENABLE_OTEL_TRACES=true`）
  - Langfuse 自动关联 LLM 调用、RAG 检索、知识库入库等业务 span
- **限流**：Redis + Lua 滑动窗口，按客户端 IP + 请求路径计数
- **断路器**：LLM 调用连续失败 ≥ 阈值自动熔断（默认 5 次），30 秒后半开探测恢复
- **幂等**：`idempotency:chat:{user_id}:{client_request_id}` Redis key，处理中返回提示、已完成返回结果 ID
- **并发**：进程内 asyncio.Semaphore 控制 LLM 与 DB 并发上限，防止单 worker 资源耗尽

## 9. 开发

```bash
# 安装
uv sync

# 代码质量
make lint        # ruff
make typecheck   # ty
make check       # lint + typecheck 组合

# 测试
make test                          # 单元 + 集成（排除 performance）
uv run pytest -m smoke             # HTTP 冒烟测试
make qa-perf-chat                  # 标准化 HTTP 性能压测
make qa-perf-chat-locust           # Locust 人工探索压测

# 诊断
uv run python scripts/diagnostics/check_ai_env.py
uv run python scripts/diagnostics/check_ai_env.py --live  # 含 LLM + embedding 实际调用
```

## 10. 常见问题

**上传文件后任务一直 `pending`**
- 确认 TaskIQ worker 已启动
- 检查 `TASKIQ_REDIS_URL` 与 API 服务 Redis 是否一致

**聊天返回"服务暂时不可用"或"已熔断保护"**
- `mock` 模式仅供联调，切换其他 provider 需配置对应的 `*_API_KEY`
- 熔断打开后等待 30 秒自动恢复，也可重启服务立即复位
- 检查 `configs/llm/models.yaml` 中 provider profile 配置是否正确

**RAG 检索为空**
- 确认文件状态已到 `ready`
- 确认 `RAG_EMBED_PROVIDER` 与 `configs/llm/models.yaml` 中 embedding profile 匹配
- embedding 维度需与数据库向量维度一致（当前默认 768）

**Langfuse 无数据**
- 确认 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL` 均已设置
