# Obsidian Mentor AI Backend（README_new）

基于当前 `backend/` 代码的后端说明文档，聚焦：可运行、可调试、可扩展。

## 1. 后端能力概览

当前后端是一个基于 FastAPI + PostgreSQL(pgvector) + Redis + TaskIQ 的异步 AI 服务，核心能力如下：

- 用户认证与权限
  - 注册、登录（JWT）
  - 当前用户信息查询
  - 超级管理员用户管理与批量导入
- 对话系统
  - 非流式问答：`/chat/query_sent`
  - SSE 流式问答：`/chat/query_stream`
  - 会话列表与会话详情查询
  - 幂等控制（`client_request_id` + Redis）
  - 用户 Token 配额控制
- 知识库 RAG
  - 知识文件上传（返回异步任务 ID）
  - TaskIQ 异步解析、切分、向量化入库
  - 任务状态查询、文件状态查询
- 可观测性与稳定性
  - 结构化 JSON 日志
  - 请求链路追踪（`X-Request-ID`）
  - Prometheus 指标 `/metrics`
  - 健康检查（存活/就绪）
  - Redis Lua 滑动窗口限流

## 2. 技术栈（与当前代码一致）

- Web: `FastAPI`, `Uvicorn`
- ORM: `SQLAlchemy (async)`
- DB: `PostgreSQL 17 + pgvector`
- Cache/Queue: `Redis`
- Async Task: `TaskIQ + taskiq-redis`
- LLM:
  - `mock`（默认）
  - `openai-compatible`（兼容外部 OpenAI-style API 网关/模型服务）
  - `deepseek`（DeepSeek OpenAI-compatible API）
  - `gemini` / `pydantic-ai`（通过 Pydantic AI 接入 Gemini）
- Embedding:
  - `google` / `gemini`（当前启用，Google GenAI embeddings）
  - `openai-compatible`（保留为外部 OpenAI-style API 后备）
- Parsing/Chunking:
  - 文本文件直接切分
  - `pypdfium2` 轻量抽取 PDF 文本

## 3. 关键目录（backend）

```text
backend/
├── main.py                      # FastAPI 入口（生命周期、路由、监控、中间件）
├── api/
│   ├── deps/                    # 依赖注入（UoW、Auth、AI、Workflow）
│   └── v1/endpoint/             # 认证/用户/聊天/知识库/健康检查接口
├── core/                        # config、db、redis、日志、异常、task broker
├── models/
│   ├── orm/                     # SQLAlchemy 模型
│   └── schemas/                 # Pydantic 请求/响应模型/DTO模型
├── repositories/                # 仓储层（User/Chat/Knowledge/Task）
├── services/                    # 领域服务（用户、会话、任务、RAG 等）
├── workflow/                    # 业务编排（聊天、上传、RAG 入库）
├── tasks/                       # TaskIQ worker 任务
├── ai/                          # Prompt、token 计数、LLM/Embedding provider
└── middleware/                  # tracing / rate limit
```

## 4. 运行前准备

### 4.1 环境要求

- Python `3.12.x`
- PostgreSQL（建议 `pgvector` 镜像）
- Redis
- `uv`（依赖管理）

### 4.2 安装依赖

```bash
uv sync
```

### 4.3 环境变量

最少需要配置（推荐放到项目根目录 `.env`）：

- 必填
  - `SECRET_KEY`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`
  - `POSTGRES_SERVER`
  - `POSTGRES_DB`
- 推荐
  - `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` 或直接 `REDIS_URL`
  - `TASKIQ_REDIS_URL`（不填则自动回退到 Redis DB1）
  - `LLM_PROVIDER`（可选覆盖 `configs/llm/models.yaml` 的 `default_profile`，第一版推荐 `gemini`）
  - `LLM_API_KEY` / `OPENAI_API_KEY`（`openai-compatible` profile 使用）
  - `GEMINI_API_KEY` / `GOOGLE_API_KEY`（`gemini` profile 使用）
  - `DEEPSEEK_API_KEY`（`deepseek` 系列 profile 使用）
  - `RAG_EMBED_PROVIDER=google`（选择 `configs/llm/models.yaml` 中的 embedding profile）
  - `RAG_EMBED_API_KEY`（可不填，默认复用 `GEMINI_API_KEY` / `GOOGLE_API_KEY`）
  - `KNOWLEDGE_STORAGE_ROOT`
- 可选监控
  - `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`
  - `LANGFUSE_BASE_URL`（Cloud EU 默认 `https://cloud.langfuse.com`；US 区通常为 `https://us.cloud.langfuse.com`）

说明：
- 代码中路由版本前缀为 `API_V1_STR=/v1`。
- 若反向代理前缀为 `API_ROOT_PATH=/api`，对外通常表现为 `/api/v1/...`。
- 本地直连开发常用 `/v1/...`。

### 4.4 应用配置文件

非敏感的 LLM 与权限策略配置放在 `configs/`：

- `configs/llm/prompts.yaml`：Jinja2 system prompt、RAG prompt、summary prompt。
- `configs/llm/models.yaml`：LLM/embedding profile、provider、model、base URL、维度、API key 环境变量名与别名。env 只负责选择 profile 和提供 secret，不再重复维护模型名。
- `configs/access/permissions.yaml`：workspace 角色到权限的映射。

默认读取项目根目录的 `configs/`，也可以通过 `CONFIG_DIR=/path/to/configs` 指向另一套配置。API 启动时会校验这些文件；缺失核心模板、未知权限、重复模型别名等都会直接启动失败。

Prompt 支持 Langfuse 同步缓存模式：

```bash
uv run python scripts/prompts/pull_from_langfuse.py --label production
```

脚本会按 `configs/llm/prompts.yaml` 中的 `langfuse.templates` 映射，从 Langfuse 拉取文本 prompt，并写入 `.cache/langfuse/prompts.production.yaml`。API 运行时优先读取该本地 cache，并按 `source.ttl_seconds` 定期重新加载；cache 不存在、损坏或未同步时，会自动降级使用 `configs/llm/prompts.yaml` 中的 fallback prompt。`.cache/` 不进 Git。

Docker smoke 环境会把宿主机 `.cache` 只读挂载到 API 与 TaskIQ worker 容器。更新 Langfuse prompt 后，重新运行拉取脚本即可让容器在 TTL 到期后读取新 cache。

常用参数：

- `--force`：忽略 TTL，强制从 Langfuse 拉取。
- `--label staging`：拉取 `staging` label。
- `--output .cache/langfuse/prompts.staging.yaml`：写入另一份 cache。

真实 AI 配置可先用诊断脚本检查：

```bash
uv run python scripts/diagnostics/check_ai_env.py
uv run python scripts/diagnostics/check_ai_env.py --live
```

默认只解析 profile、检查 key 和初始化客户端；`--live` 会实际请求一次 LLM、一次 embedding，并在 Langfuse 已配置时执行 `auth_check()`。

## 5. 本地启动

### 5.1 数据库迁移

```bash
uv run alembic upgrade head
```

### 5.2 启动 API

```bash
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5.3 启动 TaskIQ Worker（必须）

知识库入库任务与流式 LLM 任务都依赖 worker：

```bash
uv run taskiq worker backend.core.task_broker:broker backend.tasks.llm_tasks backend.tasks.knowledge_tasks --workers 2
```

## 6. 核心 API 清单

基准前缀：
- 本地直连：`/v1`
- 反向代理场景：`/api/v1`

### 6.1 Auth

- `POST /auth/register` 注册
- `POST /auth/login` 登录（OAuth2PasswordRequestForm，返回 Bearer Token）

### 6.2 Users

- `GET /users/me` 当前用户信息
- `GET /users`（超级管理员）按 `username/email` 查询单用户
- `PATCH /users/{user_id}`（超级管理员）更新用户
- `POST /users`（超级管理员）创建用户
- `POST /users/csv_upload`（超级管理员）CSV/XLSX 批量导入

### 6.3 Chat

- `POST /chat/query_sent` 非流式问答
- `POST /chat/query_stream` SSE 流式问答
- `GET /chat/sessions` 会话列表
- `GET /chat/sessions/{session_id}` 会话详情

`query_stream` SSE 事件类型：
- `meta`
- `chunk`
- `error`
- `[DONE]`

### 6.4 Knowledge

- `POST /knowledge/bases/{kb_id}/upload` 上传文件并触发异步入库（202）
- `GET /knowledge/tasks/{task_id}` 查询任务状态
- `GET /knowledge/files/{file_id}` 查询文件状态

### 6.5 Health

- `GET /health_check/live` 存活检查
- `GET /health_check/db_ready` 数据库就绪检查

### 6.6 Other

- `GET /metrics` Prometheus 指标
- `GET /debug-request` 请求调试信息

## 7. 知识库异步处理流程

`upload -> task -> parse -> chunk -> embedding -> ready`

状态流转（文件）：
- `uploaded`
- `parsing`
- `chunking`
- `ready`
- `failed`

状态流转（任务）：
- `pending`
- `processing`
- `completed`
- `failed`

支持的知识文件类型：
- 文本类：`.txt/.md/.csv/.json/.yaml/.py/.sql/...`
- PDF：`.pdf`（轻量文本抽取；扫描件/OCR 暂不在后端处理）

## 8. 数据模型摘要

- `users`: 用户、权限、Token 配额
- `chat_sessions`: 会话
- `chat_messages`: 消息（含状态、token 统计、search_context、幂等 request id）
- `knowledge_bases`: 知识库
- `knowledge_files`: 知识文件
- `document_chunks`: 切片（pgvector embedding + HNSW 索引）
- `task_jobs`: 异步任务

## 9. 观测与运维要点

- 日志：JSON 结构化输出（`orjson`）
- Trace Header：
  - 入站支持 `X-Request-ID`
  - 出站注入 `X-Request-ID`、`X-Process-Time`
- 限流：Redis + Lua 滑动窗口（按 IP + 路径）
- 聊天幂等：`idempotency:chat:{user_id}:{client_request_id}`

## 10. 开发测试

```bash
# 默认测试（排除 performance）
uv run pytest

# smoke
uv run pytest -m smoke

# performance
uv run pytest -m performance
```

## 11. 常见问题

1. 上传后任务一直 `pending`
- 检查 TaskIQ worker 是否已启动。
- 检查 `TASKIQ_REDIS_URL` 与 API 服务 Redis 是否一致。

2. 聊天接口返回“服务暂时不可用”
- 若使用 `openai-compatible`，检查 `configs/llm/models.yaml` 中的 profile，并设置 `LLM_API_KEY` 或 `OPENAI_API_KEY`。
- 若使用 DeepSeek，设置 `LLM_PROVIDER=deepseek`、`DEEPSEEK_API_KEY`；模型变体可直接用 `LLM_PROVIDER=deepseek-reasoner`、`deepseek-v4-flash` 或 `deepseek-v4-pro`。
- 若使用 Gemini，设置 `LLM_PROVIDER=gemini`、`GEMINI_API_KEY` 或 `GOOGLE_API_KEY`。
- 若只想联调链路，先把 `LLM_PROVIDER=mock`。

3. RAG 检索为空
- 检查文件是否到 `ready` 状态。
- Google 第一版推荐 `RAG_EMBED_PROVIDER=google`，并设置 `GEMINI_API_KEY`。
- 检查 `configs/llm/models.yaml` 中 embedding profile 的 `dimensions` 是否匹配库中向量维度（当前模型字段为 768 维）。

4. Langfuse 看不到 Gemini 调用
- 确认已设置 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL`。
- 当前 Gemini provider 已通过 Pydantic AI `instrument=True` 输出 OTel spans；OpenAI-compatible / DeepSeek provider、RAG 检索、知识库入库、TaskIQ worker、chat workflow 也会输出 `llm.*`、`rag.*`、`vector_index.*`、`knowledge.*`、`taskiq.*`、`chat.*` 业务 spans。
