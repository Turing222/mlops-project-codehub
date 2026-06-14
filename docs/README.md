# Project Docs

项目级文档索引。`docs/` 按**文档性质**分子目录；细节规范按**技术栈**分散在 `frontend/docs/`、`tests/` 等专属目录。

首次进入仓库：先看根目录 [README.md](../README.md)，再按角色选路径。

## 目录结构

```text
docs/
├── README.md              # 本索引
├── standards/             # 长期有效的工程规范
├── workflows/             # 开发、验证、发布流程
├── platform/              # 部署、基础设施、运维
├── reference/             # 排错与查阅笔记
├── assessments/           # 带日期的评审 / 评估报告（时点快照）
├── legacy/                # 历史保留文档
└── todos/                 # 临时任务说明（完成后删除或归档）
```

## 推荐阅读路径

### 新后端贡献者

1. [standards/backend-interface-style.md](standards/backend-interface-style.md)
2. [standards/async-default-style.md](standards/async-default-style.md)
3. [../tests/README.md](../tests/README.md)
4. [workflows/static-test-node.md](workflows/static-test-node.md)
5. [workflows/dev-test-flow.md](workflows/dev-test-flow.md)

### 做接口 / 业务改动

1. [standards/backend-interface-style.md](standards/backend-interface-style.md)
2. [standards/automation-standard.md](standards/automation-standard.md)
3. [../tests/README.md](../tests/README.md)
4. [../tests/CONVENTIONS.md](../tests/CONVENTIONS.md)
5. [workflows/dev-test-flow.md](workflows/dev-test-flow.md)

### 做 smoke / 发布验证

1. [workflows/static-test-node.md](workflows/static-test-node.md)
2. [workflows/dev-test-flow.md](workflows/dev-test-flow.md)
3. [../tests/README.md](../tests/README.md)
4. [../deploy/k8s/README.md](../deploy/k8s/README.md)

### 做部署 / 扩缩容

1. [platform/deploy-ec2.md](platform/deploy-ec2.md)
2. [platform/k8s-scaling-strategy.md](platform/k8s-scaling-strategy.md)
3. [../deploy/k8s/README.md](../deploy/k8s/README.md)
4. [../deploy/k8s/local-scaling/README.md](../deploy/k8s/local-scaling/README.md)

---

## standards/ — 工程规范

长期有效，代码风格与架构边界以此为准。

| 文档 | 说明 |
|------|------|
| [async-default-style.md](standards/async-default-style.md) | async 风格、边界和默认约定 |
| [backend-interface-style.md](standards/backend-interface-style.md) | 后端接口风格、层次边界和返回约定 |
| [automation-standard.md](standards/automation-standard.md) | 自动化分层：Makefile、scripts、CI 约定 |
| [api-review-tips.md](standards/api-review-tips.md) | API review 轻量检查清单 |

## workflows/ — 流程

「怎么做」的执行顺序与通过标准。

| 文档 | 说明 |
|------|------|
| [dev-test-flow.md](workflows/dev-test-flow.md) | 从改代码到 smoke 验证的推荐顺序 |
| [static-test-node.md](workflows/static-test-node.md) | 静态检查与验证节点说明 |

关联入口：[../tests/README.md](../tests/README.md)、[../tests/CONVENTIONS.md](../tests/CONVENTIONS.md)

## platform/ — 部署与基础设施

生产拓扑、发布路径、密钥与扩缩容。

| 文档 | 说明 |
|------|------|
| [deploy-ec2.md](platform/deploy-ec2.md) | EC2 手动部署与 CD 对接（**当前生产主路径**） |
| [frontend-delivery-and-edge-responsibilities.md](platform/frontend-delivery-and-edge-responsibilities.md) | Cloudflare Pages、API origin、容器 fallback 职责 |
| [api-keys-and-degradation.md](platform/api-keys-and-degradation.md) | API Key 分层、功能映射、缺失/故障降级 |
| [k8s-scaling-strategy.md](platform/k8s-scaling-strategy.md) | API / worker 扩缩容策略 |
| [deploy-hardening-backlog.md](platform/deploy-hardening-backlog.md) | 部署加固待办（完成即删） |

关联入口：[../deploy/k8s/README.md](../deploy/k8s/README.md)、[../deploy/monitoring/](../deploy/monitoring/)

## reference/ — 参考与排错

非规范性的查阅笔记，遇问题时翻。

| 文档 | 说明 |
|------|------|
| [sqlalchemy-async-pitfalls.md](reference/sqlalchemy-async-pitfalls.md) | SQLAlchemy async 常见陷阱 |

## assessments/ — 评审与评估

**带日期的时点报告**，记录某次审计结论与证据；不等同于现行规范。新规范应沉淀到 `standards/` 或 `platform/`。

| 文档 | 说明 |
|------|------|
| [frontend-cicd-assessment-2026-06-14.md](assessments/frontend-cicd-assessment-2026-06-14.md) | 前端 CI/CD 评估与改造建议 |
| [backend-resilience-eval-2026-06-14.md](assessments/backend-resilience-eval-2026-06-14.md) | 后端韧性评估 |
| [doc-audit-2026-06-12.md](assessments/doc-audit-2026-06-12.md) | 文档准确性审计 |
| [skill-agent-mcp-eval-2026-06-12.md](assessments/skill-agent-mcp-eval-2026-06-12.md) | Skill / Agent / MCP 评估 |

## legacy/ — 历史保留

| 文档 | 说明 |
|------|------|
| [README.backend-legacy.md](legacy/README.backend-legacy.md) | 旧版根 README 副本，偏后端手册视角 |

## todos/ — 临时任务

| 文档 | 说明 |
|------|------|
| [todo-storage-column-types.md](todos/todo-storage-column-types.md) | 存储列类型迁移待办 |

---

## 其他一级入口

按技术域维护细节，`docs/` 只做索引跳转：

| 目录 | 内容 |
|------|------|
| [../frontend/docs/README.md](../frontend/docs/README.md) | 前端架构、迁移计划、编码标准 |
| [../frontend/apps/admin/README.md](../frontend/apps/admin/README.md) | admin 应用开发与验证 |
| [../design/README.md](../design/README.md) | 跨平台设计 token 与 L1 清单 |
| [../evals/README.md](../evals/README.md) | RAG 评测 |
| [../perf/README.md](../perf/README.md) | 性能压测 |

## 维护约定

- **放哪**：长期规范 → `standards/`；流程 → `workflows/`；部署运维 → `platform/`；一次性评审 → `assessments/`；临时任务 → `todos/`。
- **不放哪**：前端编码细节 → `frontend/docs/`；可归档工作项 → `work-items/`。
- **语言**：正文中文；代码标识、命令、字段名保留英文。
- **索引**：Makefile 或目录结构变化时，同步更新根 [README.md](../README.md) 与本文件。
- **评估报告**：结论已落地则把规范写入 `standards/` / `platform/`，评估原文保留作历史。
