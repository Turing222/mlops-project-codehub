# Project Docs

这个目录用于承载项目级规范、开发/验证流程、参考笔记和平台设计说明。它不是单一主题手册，而是 Dewflow 仓库内部文档的**索引入口**。

如果你是第一次进入这个仓库，建议先看根目录 [README.md](../README.md)，再回到这里按角色继续阅读。

## 推荐阅读路径

### 新后端贡献者
1. [backend-interface-style.md](backend-interface-style.md)
2. [async-default-style.md](async-default-style.md)
3. [../tests/README.md](../tests/README.md)
4. [static-test-node.md](static-test-node.md)
5. [dev-test-flow.md](dev-test-flow.md)

### 做接口 / 业务改动的人
1. [backend-interface-style.md](backend-interface-style.md)
2. [automation-standard.md](automation-standard.md)
3. [../tests/README.md](../tests/README.md)
4. [../tests/CONVENTIONS.md](../tests/CONVENTIONS.md)
5. [dev-test-flow.md](dev-test-flow.md)

### 做 smoke / 发布验证的人
1. [static-test-node.md](static-test-node.md)
2. [dev-test-flow.md](dev-test-flow.md)
3. [../tests/README.md](../tests/README.md)
4. [../deploy/k8s/README.md](../deploy/k8s/README.md)

### 做部署 / 扩缩容相关工作的人
1. [deploy-ec2.md](deploy-ec2.md)
2. [k8s-scaling-strategy.md](k8s-scaling-strategy.md)
3. [../deploy/k8s/README.md](../deploy/k8s/README.md)
4. [../deploy/k8s/local-scaling/README.md](../deploy/k8s/local-scaling/README.md)

## 文档分类索引

## Engineering Standards

- [async-default-style.md](async-default-style.md) — async 风格、边界和默认约定。
- [backend-interface-style.md](backend-interface-style.md) — 后端接口风格、层次边界和返回约定。
- [automation-standard.md](automation-standard.md) — 自动化、验证层次和脚本/Makefile 约定。

## Development & Validation Workflow

- [dev-test-flow.md](dev-test-flow.md) — 从代码修改到 smoke 验证的推荐执行顺序。
- [static-test-node.md](static-test-node.md) — 静态检查与验证节点说明。
- [../tests/README.md](../tests/README.md) — 测试分层与推荐命令。
- [../tests/CONVENTIONS.md](../tests/CONVENTIONS.md) — 测试目录、marker、fixture 与环境细则。

## Reference / Troubleshooting

- [sqlalchemy-async-pitfalls.md](sqlalchemy-async-pitfalls.md) — SQLAlchemy async 常见陷阱与修正建议。
- [api-review-tips.md](api-review-tips.md) — API review 时的轻量检查清单。

## Platform / Deployment Notes

- [deploy-ec2.md](deploy-ec2.md) — 单台 EC2 的手动部署入口与后续自动 CD 对接方式。
- [api-keys-and-degradation.md](api-keys-and-degradation.md) — API Key 需求分层、key→功能映射，以及缺失/故障时的告警与降级行为。
- [k8s-scaling-strategy.md](k8s-scaling-strategy.md) — API / worker 扩缩容策略说明。
- [../deploy/k8s/README.md](../deploy/k8s/README.md) — Kubernetes 接入与部署示例。
- [../deploy/k8s/local-scaling/README.md](../deploy/k8s/local-scaling/README.md) — 本地 worker 扩缩容演示。

## Legacy / Temporary Notes

- [README.backend-legacy.md](README.backend-legacy.md) — 旧版根 README 的保留副本，偏后端手册视角。
- [todo-storage-column-types.md](todo-storage-column-types.md) — 临时任务记录；这是一个待处理迁移说明，不属于稳定规范文档。

## 相关文档入口

除了 `docs/` 目录，下面这些也是常用的一级入口：

- [../frontend/docs/README.md](../frontend/docs/README.md) — 前端架构与标准索引。
- [../frontend/apps/admin/README.md](../frontend/apps/admin/README.md) — admin 应用开发与验证入口。
- [../evals/README.md](../evals/README.md) — RAG 评测流程。
- [../perf/README.md](../perf/README.md) — 性能压测工具与报告说明。

## 维护约定

- `docs/` 优先放长期有效的规范、流程和参考资料。
- `work-items/` 用于可推进、可结束、可归档的工作项（work item）产物与 checkpoint；不要把长期规范沉淀到这里。
- 临时任务说明可以保留，但应像 [todo-storage-column-types.md](todo-storage-column-types.md) 一样明确标识其临时性质。
- 项目文档正文使用中文；代码标识、命令、字段名、状态枚举和常用技术术语保留英文。`work-items/*/manifest.yaml` 作为 agent 状态源保持英文，`task-plan.md` 使用中文叙事。
- 当代码结构或 Makefile 入口发生变化时，优先更新根目录 [README.md](../README.md) 与本索引，避免导航层先过时。
- 如果某篇文档已经属于某个子领域的专属说明（例如 frontend、tests、evals、perf），优先在对应目录维护细节，这里只保留索引链接。
