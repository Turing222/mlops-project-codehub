# Dewflow

Dewflow 仓库当前包含后端服务、前端管理端、测试体系、RAG 评测与性能验证工具。这个 README 现在作为**仓库级入口页**使用，帮助你快速找到启动方式、验证命令和更深入的专题文档。

> 旧版偏后端手册式 README 已保留在 [docs/README.backend-legacy.md](docs/README.backend-legacy.md)，暂时不删除，供历史参考与补充查阅。

## 仓库结构概览

| 目录 | 作用 |
| --- | --- |
| [backend/](backend/) | FastAPI API、应用编排、领域服务、基础设施适配器与 worker 任务。 |
| [frontend/](frontend/) | 前端工作区，当前主要应用为 admin。 |
| [tests/](tests/) | 自动化测试分层与测试约定。 |
| [evals/](evals/) | RAG 检索、规划、回答质量评测工具。 |
| [perf/](perf/) | 标准化负载压测与性能报告。 |
| [deploy/](deploy/) | Docker / Kubernetes 部署示例与运行材料。 |
| [configs/](configs/) | 非敏感配置与 provider/profile 定义。 |
| [docs/](docs/) | 项目级规范、流程、参考说明与文档索引。 |
| [work-items/](work-items/) | 项目级任务、checkpoint 与跨对话协作产物。 |

## Start Here

### 1. 安装依赖

```bash
uv sync
```

如果要运行前端，还需要安装 Node / pnpm 环境；前端细节见 [frontend/apps/admin/README.md](frontend/apps/admin/README.md)。

### 2. 启动本地基础依赖

```bash
docker compose -f docker-compose.db.yml up -d
```

如果你准备走标准 smoke/local 验证流，优先参考 [docs/dev-test-flow.md](docs/dev-test-flow.md) 和 `make env-smoke-*` 相关命令。

### 3. 迁移数据库

```bash
uv run alembic upgrade head
```

### 4. 启动 API

```bash
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 启动 worker

```bash
uv run taskiq worker backend.infra.task_broker:broker backend.worker.tasks.llm_tasks backend.worker.tasks.knowledge_tasks backend.worker.tasks.repo_analysis_tasks --workers 2
```

### 6. 启动前端（可选）

```bash
pnpm --dir frontend --filter admin dev
```

更完整的前端运行、构建与 e2e 说明见：
- [frontend/apps/admin/README.md](frontend/apps/admin/README.md)
- [frontend/docs/README.md](frontend/docs/README.md)

## 常用命令

以下命令来自根目录 [Makefile](Makefile)，适合作为当前项目的高频入口：

```bash
make flow-fast              # 快速反馈：后端静态检查 + 单测/组件测试 + 前端检查
make flow-local             # 本地完整验证：flow-fast + smoke stack + integration + e2e
make frontend-check         # 前端 lint + typecheck + test + build
make qa-test-unit           # 后端单元测试
make qa-test-integration    # 后端集成测试
make qa-eval-rag            # RAG 检索/回答评测
make qa-perf-chat           # 标准化 chat API 压测
```

如果你不确定当前改动该跑哪条验证链路，先看 [tests/README.md](tests/README.md) 和 [docs/dev-test-flow.md](docs/dev-test-flow.md)。

## 文档导航

### 仓库与项目文档入口
- [docs/README.md](docs/README.md) — 项目级规范、流程、参考文档索引
- [docs/README.backend-legacy.md](docs/README.backend-legacy.md) — 保留的旧版后端主视角 README

### 测试、评测与性能
- [tests/README.md](tests/README.md) — 测试分层与推荐命令
- [tests/CONVENTIONS.md](tests/CONVENTIONS.md) — 更细的测试约定
- [evals/README.md](evals/README.md) — RAG 评测流程
- [perf/README.md](perf/README.md) — 性能压测入口与报告说明

### 前端
- [frontend/apps/admin/README.md](frontend/apps/admin/README.md) — admin 应用开发与验证入口
- [frontend/docs/README.md](frontend/docs/README.md) — 前端架构、迁移计划与标准索引

### 部署与运行
- [deploy/k8s/README.md](deploy/k8s/README.md) — Kubernetes 接入示例
- [deploy/k8s/local-scaling/README.md](deploy/k8s/local-scaling/README.md) — 本地 worker 自动扩缩容演示
- [secrets/smoke/README.md](secrets/smoke/README.md) — smoke secrets 使用说明

## 文档使用建议

- 想快速理解仓库：先读本页，再进入 [docs/README.md](docs/README.md)。
- 想开始开发/提测：优先看 [tests/README.md](tests/README.md) 与 [docs/dev-test-flow.md](docs/dev-test-flow.md)。
- 想看前端约定：从 [frontend/docs/README.md](frontend/docs/README.md) 开始。
- 想查历史后端细节：看 [docs/README.backend-legacy.md](docs/README.backend-legacy.md)。

## 说明

这个根 README 现在刻意只保留**低漂移的导航信息**，不再重复完整 API 清单、全量环境变量表或细粒度运维说明；这些内容应优先由专题文档承载，以降低文档与代码结构漂移的风险。
