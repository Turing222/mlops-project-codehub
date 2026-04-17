# 自动化标准

本文档定义本项目以及后续同类项目可复用的自动化实现标准，重点解决以下问题：

- 哪些内容属于 `Makefile`
- 哪些内容属于 `scripts/`
- 文档、命令入口、脚本实现和 CI 如何保持一致
- 测试、构建、Smoke 验证这类流程应该如何命名和分层

本文档偏“工程实现标准”，用于长期复用和重复阅读。

相关规范：

- [async-default-style.md](./async-default-style.md)

## 1. 设计目标

自动化体系应满足以下要求：

- 有唯一的公开命令入口
- 本地执行和 CI 执行尽量共用同一套命令
- 简单动作容易调用，复杂流程容易维护
- 文档与实现保持一致，不出现“双轨逻辑”
- 可以从小项目逐步演进到中型项目，而不需要推倒重来

## 2. 分层职责

### `docs/`

职责：

- 定义流程和规范
- 说明执行顺序、通过标准和失败处理
- 解释目录职责和命名约定

回答的问题：

- 我们应该怎么做
- 为什么这样做

### 根目录 `Makefile`

职责：

- 提供统一命令入口
- 作为开发者和 CI 的共同调用界面
- 暴露稳定、短、易记的命令名

回答的问题：

- 我应该敲什么命令

原则：

- `Makefile` 是公开入口，不是复杂业务逻辑的容器
- 简单动作直接放在 `Makefile`
- 复杂流程通过 `Makefile` 调用脚本

### `scripts/`

职责：

- 承载复杂 shell 编排
- 封装等待、重试、超时、日志输出、清理动作
- 作为 `Makefile` 背后的实现层

回答的问题：

- 这条命令背后具体怎么执行

原则：

- `scripts/` 属于工程自动化资产
- `scripts/` 不属于后端业务代码，但属于项目的一部分
- 与部署、测试、构建、排障相关的复杂 shell 逻辑优先放在这里

### CI

职责：

- 调用已经在本地存在的标准入口
- 复用 `Makefile` 或脚本

回答的问题：

- 机器如何按同样规则执行

原则：

- CI 不重新发明一套流程
- 优先复用本地已经跑通的命令

## 3. 推荐目录结构

```text
.
├── Makefile
├── docs/
│   ├── dev-test-flow.md
│   └── automation-standard.md
├── scripts/
│   ├── lib/
│   │   └── common.sh
│   ├── qa/
│   │   ├── run_unit.sh
│   │   ├── run_integration.sh
│   │   └── run_checks.sh
│   ├── image/
│   │   └── build_backend.sh
│   ├── smoke/
│   │   ├── up.sh
│   │   ├── wait.sh
│   │   ├── test.sh
│   │   └── down.sh
│   └── flow/
│       └── dev_check.sh
```

目录说明：

- `scripts/lib/`: 公共函数和通用工具
- `scripts/qa/`: 单元测试、集成测试、静态检查
- `scripts/image/`: 镜像构建相关脚本
- `scripts/smoke/`: Smoke 环境启停和验证
- `scripts/flow/`: 串联整条流水线

## 4. 命名规范

建议使用“能力域 + 动作”的命名方式。

推荐分组如下：

### QA 质量检查

- `qa-lint`
- `qa-format`
- `qa-typecheck`
- `qa-test-unit`
- `qa-test-integration`
- `qa-test-all`
- `qa-checks`

### 镜像构建

- `image-build`

### 环境生命周期

- `env-smoke-up`
- `env-smoke-wait`
- `env-smoke-down`
- `env-smoke-logs`

### 验证动作

- `verify-smoke`

### 流程聚合

- `flow-dev-check`
- `flow-ci`

命名原则：

- 目标名保持稳定
- 面向职责命名，不面向个人习惯命名
- 名称应能直接表达“这一步做什么”

## 5. 什么时候放 `Makefile`

适合直接放在 `Makefile` 的情况：

- 一条命令就能表达清楚
- 使用频率高，团队成员会直接调用
- 不需要复杂的条件判断
- 不需要等待、重试、超时控制

典型例子：

- `uv run ruff check .`
- `uv run ty check .`
- `docker build -t ... .`
- `docker compose -f ... up -d`
- `docker compose -f ... down`

## 6. 什么时候放 `scripts/`

适合放在 `scripts/` 的情况：

- 需要执行多步命令
- 需要 `set -euo pipefail`
- 需要等待服务健康
- 需要失败后自动打印日志
- 需要清理环境
- 需要条件判断、重试或超时

典型例子：

- 等待 Smoke 环境 ready
- 运行多条 HTTP Smoke 检查
- 一键串联“测试 -> 构建 -> 启动环境 -> 验证 -> 清理”
- 失败时输出 `docker compose logs`

## 7. `Makefile` 与脚本的联动方式

标准方式是：

- `Makefile` 暴露目标
- 目标内部调用 `scripts/*.sh`

例如：

```makefile
qa-test-unit:
	bash scripts/qa/run_unit.sh

env-smoke-up:
	bash scripts/smoke/up.sh

verify-smoke:
	bash scripts/smoke/test.sh

flow-dev-check:
	bash scripts/flow/dev_check.sh
```

这样做的好处：

- 开发者使用简单
- 脚本逻辑容易维护
- CI 可以直接复用 `make`

## 8. 推荐实现方式

### 原子命令

这些目标应当保持“单一职责”：

- `qa-test-unit`
- `qa-test-integration`
- `qa-lint`
- `qa-typecheck`
- `image-build`
- `env-smoke-up`
- `env-smoke-wait`
- `env-smoke-down`
- `verify-smoke`

### 聚合命令

这些目标负责串起一条完整流程：

- `flow-dev-check`
- `flow-ci`

推荐策略：

- 原子命令可单独运行
- 聚合命令只组合原子命令，不重复定义底层逻辑

## 9. 推荐执行链路

开发验证主链路：

```text
qa-test-unit
-> qa-test-integration
-> qa-lint
-> qa-typecheck
-> image-build
-> env-smoke-up
-> env-smoke-wait
-> verify-smoke
-> env-smoke-down
```

这条链路应同时适用于：

- 本地提交前验证
- 手工回归
- 后续 CI

## 10. 环境变量和配置传递

为了便于复用，推荐在 `Makefile` 中定义公共变量并导出给脚本，例如：

- `DOCKER_IMAGE_NAME`
- `SMOKE_COMPOSE_FILE`
- `SMOKE_BASE_URL`
- `SMOKE_LIVE_PATH`
- `SMOKE_READY_PATH`

这样可以做到：

- 默认值可用
- 特定环境可覆盖
- 脚本实现不需要写死路径和镜像名

## 11. 复用原则

未来复用这套标准时，优先保留以下不变项：

- 根目录 `Makefile` 作为唯一公开入口
- `scripts/` 作为复杂编排层
- 文档先行，自动化实现后跟
- 命名分层保持一致

可以按项目差异调整的内容：

- `docker compose` 文件名
- 镜像名
- Smoke 检查接口
- 测试目录范围

## 12. 本项目的落地要求

本项目当前应遵循以下落地方式：

- 文档说明使用 [dev-test-flow.md](/home/tongying/workspace/mlops-project/docs/dev-test-flow.md)
- 自动化标准使用本文档
- 实际入口统一通过 [Makefile](/home/tongying/workspace/mlops-project/Makefile)
- 复杂逻辑放在 `scripts/`
- 后续 CI 复用同一套入口

一句话总结：

`docs` 负责定义规则，`Makefile` 负责暴露入口，`scripts` 负责执行细节，CI 负责复用这套入口。
