# 项目全景上下文 (Project Context - 2026 Edition)

这是为 AI 助手（Antigravity）准备的项目记忆库，涵盖了项目的架构、技术栈、环境配置及操作规范。

## 1. 项目概况
- **项目名称**: AI Tutor / MLOps Project
- **核心目标**: 构建一个支持向量检索（RAG）、多模型切换、文件处理及用户管理的 AI 导师系统。
- **架构模式**: 
  - **后端**: FastAPI (Python 3.12) + DDD (领域驱动设计) 分层架构。
  - **前端**: Monorepo 结构，包含 `portal` (用户端) 和 `admin` (管理端)。
  - **数据库**: PostgreSQL 17 (带 pgvector 扩展) + Redis 7.4。

## 2. 技术栈详解
- **底层管理**: `uv` (Python 包及虚拟环境管理)。
- **后端核心**: 
  - 异步支持: `sqlalchemy[asyncio]`, `asyncpg`。
  - AI 能力: `ollama`, `openai`, `sentence-transformers`, `docling` (文档解析)。
  - 认证: `bcrypt`, `pyjwt`, `pwdlib`。
- **运维与可观察性**:
  - 日志中转: `Vector` (timberio/vector:0.44.0+)。
  - 日志存储: `Loki` (grafana/loki:3.4.0)。
  - 指标监控: `Prometheus` (prom/prometheus:v3.8.1) + `Grafana` (grafana/grafana-oss)。

## 3. 环境与部署配置 (WSL2)
- **运行环境**: WSL2 (Ubuntu 24.04)，宿主机预留 6GB 内存。
- **Docker 网络**:
  - `app_net`: 业务服务（API, DB, Redis）互通。
  - `monitor_net`: 监控流量隔离。
- **资源限制原则**: 
  - `api`: Limit 800M / Reserve 256M。
  - `postgres`: Limit 1024M / Reserve 256M。
  - 其他监控组件均配有相应的 Memory Limits & Reservations (128M - 512M)。
- **核心端口映射**:
  - Nginx: `80`, `443` (前端入口与反向代理)。
  - API (本地直连): `8000` (路径前缀 `/api`)。

## 4. 关键验证规则 (SOP)
- **命令前缀**: 任何 Python 相关的操作必须使用 `uv run`。
- **禁止动作**: **严禁**使用 Browser 工具访问 `localhost`，应使用 `curl` 结合容器日志进行诊断。
- **验证链接**: 
  - 存活检查: `http://localhost:8000/api/v1/health_check/live`
  - 调试接口: `http://localhost:8000/api/debug-request`

## 5. 项目结构索引
- `/backend`: 
  - `api/v1`: 路由定义。
  - `models/orm`: 数据库实体（User, Chat, File, Task）。
  - `services`: 业务逻辑（ChatService, LLMService, Ingestion）。
  - `workflow`: 复杂逻辑编排。
- `/deploy`: Docker Compose 配置及环境变量。
- `/frontend/apps`: `portal` 与 `admin` 前端源码。

## 6. 安全策略
- **Nginx 安全响应头**: `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security` 等已在 `project.conf` 中定义。
- **用户模型**: 采用 UID/GID (如 1000:1000) 映射，确保容器内非 root 运行。
