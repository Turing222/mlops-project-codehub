# 项目文档

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
└── legacy/                # 历史保留文档
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
| --- | --- |
| [async-default-style.md](standards/async-default-style.md) | async 风格、边界和默认约定 |
| [backend-interface-style.md](standards/backend-interface-style.md) | 后端接口风格、层次边界和返回约定 |
| [automation-standard.md](standards/automation-standard.md) | 自动化分层：Makefile、scripts、CI 约定 |
| [api-review-checklist.md](standards/api-review-checklist.md) | API review 轻量检查清单 |

## workflows/ — 流程

「怎么做」的执行顺序与通过标准。

| 文档 | 说明 |
| --- | --- |
| [dev-test-flow.md](workflows/dev-test-flow.md) | 从改代码到 smoke 验证的推荐顺序 |
| [ci-test-matrix.md](workflows/ci-test-matrix.md) | 本地验证 ↔ CI 分层矩阵、合并门禁与分期路线图 |
| [pr-description.md](workflows/pr-description.md) | PR 描述模板（小 PR / 大 PR）与 `make pr-report` 分工 |
| [static-test-node.md](workflows/static-test-node.md) | 静态检查与验证节点说明 |

关联入口：[../tests/README.md](../tests/README.md)、[../tests/CONVENTIONS.md](../tests/CONVENTIONS.md)

## platform/ — 部署与基础设施

生产拓扑、发布路径、密钥与扩缩容。

| 文档 | 说明 |
| --- | --- |
| [deploy-ec2.md](platform/deploy-ec2.md) | EC2 手动部署与 CD 对接（**当前生产主路径**） |
| [frontend-delivery-and-edge-responsibilities.md](platform/frontend-delivery-and-edge-responsibilities.md) | Cloudflare Pages、API origin、容器 fallback 职责 |
| [api-keys-and-degradation.md](platform/api-keys-and-degradation.md) | API Key 分层、功能映射、缺失/故障降级 |
| [k8s-scaling-strategy.md](platform/k8s-scaling-strategy.md) | API / worker 扩缩容策略 |
| [rds-backup-and-restore.md](platform/rds-backup-and-restore.md) | RDS snapshot、PITR 与恢复演练 runbook |
| [infrastructure-image-maintenance.md](platform/infrastructure-image-maintenance.md) | 基础设施镜像钉版与季度核查 |
| [local-production-rehearsal.md](platform/local-production-rehearsal.md) | EC2 上线前的本地生产形态演练 |

关联入口：[../deploy/k8s/README.md](../deploy/k8s/README.md)、[../deploy/monitoring/](../deploy/monitoring/)

## reference/ — 参考与排错

非规范性的查阅笔记，遇问题时翻。

| 文档 | 说明 |
| --- | --- |
| [sqlalchemy-async-pitfalls.md](reference/sqlalchemy-async-pitfalls.md) | SQLAlchemy async 常见陷阱 |

## assessments/ — 评审与评估

**带日期的时点报告**，记录某次审计结论与证据；不等同于现行规范。查当前做法时，应回到 `standards/`、`workflows/` 或 `platform/`。评估结论落地后，把长期约定写入对应目录，原报告保留为历史证据。

文件名统一使用 `YYYY-MM-DD-<topic>.md`，便于按时间排序。

| 文档 | 说明 |
| --- | --- |
| [2026-07-17-backend-consolidated-upgrade-roadmap.md](assessments/2026-07-17-backend-consolidated-upgrade-roadmap.md) | 汇总五份后端评估的三档升级路线、决策门、依赖、上线门槛与停止边界 |
| [2026-07-17-identity-governance-test-ci-quality.md](assessments/2026-07-17-identity-governance-test-ci-quality.md) | 登录、Workspace RBAC、审计、Credits、Feature Flags 与测试/CI/代码质量时点评估 |
| [2026-07-17-deployment-resilience-observability-security.md](assessments/2026-07-17-deployment-resilience-observability-security.md) | EC2 / Pages / K8s、Redis / TaskIQ、降级、告警、CSP、secret 与恢复能力时点评估 |
| [2026-07-17-product-domain-end-to-end-business-map.md](assessments/2026-07-17-product-domain-end-to-end-business-map.md) | 认证、用户、Workspace、权限、聊天、知识库、仓库分析与积分的当前业务地图及收敛建议 |
| [2026-07-15-chat-rag-worker-reliability-plan.md](assessments/2026-07-15-chat-rag-worker-reliability-plan.md) | Chat / RAG / Worker 主链路状态一致性、恢复、安全、质量与重构实施路线图 |
| [2026-07-15-knowledge-ingestion-data-consistency-plan.md](assessments/2026-07-15-knowledge-ingestion-data-consistency-plan.md) | 知识入库、存储、索引血缘、迁移与数据一致性改造计划 |
| [2026-07-14-agent-scaffold-security.md](assessments/2026-07-14-agent-scaffold-security.md) | 双 Agent 脚手架安全、权限与治理复核 |
| [2026-07-10-codex-plugin-extraction.md](assessments/2026-07-10-codex-plugin-extraction.md) | Codex Plugin 提取边界、候选分组与迁移建议 |
| [2026-06-14-frontend-cicd.md](assessments/2026-06-14-frontend-cicd.md) | 前端 CI/CD 评估与改造建议 |
| [2026-06-14-backend-resilience.md](assessments/2026-06-14-backend-resilience.md) | 后端韧性评估 |
| [2026-06-12-documentation-audit.md](assessments/2026-06-12-documentation-audit.md) | 文档准确性审计 |
| [2026-06-12-skill-agent-mcp.md](assessments/2026-06-12-skill-agent-mcp.md) | Skill / Agent / MCP 评估 |

## legacy/ — 历史保留

| 文档 | 说明 |
| --- | --- |
| [backend-overview-legacy.md](legacy/backend-overview-legacy.md) | 旧版根 README 副本，偏后端手册视角 |

---

## 其他一级入口

按技术域维护细节，`docs/` 只做索引跳转：

| 目录 | 内容 |
| --- | --- |
| [../frontend/docs/README.md](../frontend/docs/README.md) | 前端架构、迁移计划、编码标准 |
| [../frontend/apps/admin/README.md](../frontend/apps/admin/README.md) | admin 应用开发与验证 |
| [../design/README.md](../design/README.md) | 跨平台设计 token 与 L1 清单 |
| [../evals/README.md](../evals/README.md) | RAG 评测 |
| [../perf/README.md](../perf/README.md) | 性能压测 |

## 维护约定

- **放哪**：长期规范 → `standards/`；流程 → `workflows/`；部署运维 → `platform/`；一次性评审 → `assessments/`。
- **不放哪**：前端编码细节 → `frontend/docs/`；任务、backlog 和跨会话计划 → `work-items/`。
- **命名**：常驻文档使用 lowercase kebab-case；日期快照使用 `YYYY-MM-DD-<topic>.md`；历史冻结文档使用 `<topic>-legacy.md`。
- **语言**：正文中文；代码标识、命令、字段名保留英文。
- **索引**：本文件是 `docs/` 的唯一中央索引；新增、重命名或归档文档时只维护本文件，不在分类目录重复维护清单。
- **标题**：每篇文档只使用一个 H1；长报告可以编号章节，但同一篇内必须连续一致。
- **代码块**：所有 fenced code block 都标注语言；纯输出或示意文本使用 `text`。
- **表格**：分隔行统一写成 `| --- | --- |`，按实际列数扩展。
- **空白**：标题、列表、表格和代码块前后保留空行，不保留行尾空格。
- **评估报告**：开头统一记录日期、范围、性质、证据基线和冻结状态；结论落地后把规范写入长期目录，不继续改写历史快照。
- **校验**：文档变更后运行 `make qa-docs`；该检查也包含在 `make qa-standards-fast` 中。
