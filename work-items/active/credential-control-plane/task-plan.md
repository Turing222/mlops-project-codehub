# 工作项计划：凭据控制面与文件兼容迁移

> 机读状态只保存在 `manifest.yaml`，并以它为准。本文件记录稳定的设计结论与边界。

## 目标

将生产凭据的事实来源收敛到 AWS，同时保留 Dewflow 已有的 `FOO_FILE` 和单目录文件布局，使应用、Compose 与人工部署入口不需要理解 Secrets Manager，并让切换过程可验证、可回退。

## 对话结论

- 不按 OpenAI、Google 等供应商拆分 Secret；每个环境以 runtime bundle 为主要应用凭据单元。
- Secrets Manager 中使用 JSON，键名与现有 `*.txt` basename 建立确定映射。
- 部署时将 bundle 展开到主机临时目录，再由现有 Compose 映射到容器 `/run/secrets/*`。
- 缺失的可选键生成空文件；`SECRET_KEY`、PostgreSQL 与 Redis 密码必须非空。
- AWS、GitHub、Cloudflare 的人类管理员凭据不进入 runtime bundle。
- S3 长期 Access Key 不迁移，生产 EC2 最终使用 instance role。
- 迁移验证前不删除旧文件、不覆盖或删除现有 SSM 参数，也不撤销任何现有凭据。

## Workstream 拆分理由

### WS1 — Freeze the legacy file compatibility and migration contract

- Scope：盘点文件名、必需项、空文件语义、权限模型与当前 AWS 元数据。
- Reason：先冻结兼容契约，避免导入时改变现有容器行为。
- Expected effect：AWS JSON 与现有文件之间存在唯一、可验证的映射。

### WS2 — Implement bundle import, status, and materialization tooling with tests

- Scope：新增 allowlist manifest、导入、状态检查、materialize 逻辑和单元测试。
- Reason：所有敏感写入先通过本地确定性测试，且命令不得输出 secret value。
- Expected effect：同一工具可安全处理 legacy directory 与 Secrets Manager JSON。

### WS3 — Wire the ephemeral deploy directory and document operator workflows

- Scope：复用 `DEPLOY_SECRET_DIR`，将 EC2 运行时目录指向 `/run/dewflow-secrets`，更新部署说明。
- Reason：保持容器接口不变，同时避免把 AWS 拉取结果长期保存在仓库目录。
- Expected effect：现有 `deploy-ec2-check` 与 Compose 无需了解上游 Secret 来源。

### WS4 — Provision AWS secrets and the least-privilege EC2 retrieval path

- Scope：创建 runtime Secret、EC2 instance role 读取策略和所需标签；automation
  凭据在消费者和权限范围确认后单独处理。
- Reason：人类、CD 与运行时身份必须分离，EC2 不保存长期 AWS Access Key。
- Expected effect：生产实例只能读取明确授权的 runtime Secret。

### WS5 — Validate cutover and reconcile legacy file and SSM sources

- Scope：执行无值泄露的一致性检查、materialize、部署校验和受控切换。
- Reason：当前 PostgreSQL 密码可能同时存在于文件和 SSM，必须先确认再收敛。
- Expected effect：AWS 成为唯一事实来源，旧来源只在明确批准后退役。

## 暂缓 / 不纳入范围

- 本工作项不自动轮换第三方供应商 Token。
- 本工作项不删除历史文件、SSM 参数或本地 Cloudflare Token。
- 本工作项不把人类超级管理员和 break-glass 凭据交给应用或 CD。

## Open Decisions 说明

- `production-cutover-release`：当前改动尚未发布到生产主机，不能先改
  `DEPLOY_SECRET_SOURCE`，否则远端没有 materialize 工具。
- `legacy-source-retirement`：AWS-backed path 完成切换和观察期前，不删除或覆盖
  任何 legacy source。
- `automation-secret-scope`：Cloudflare/CD Token 不进入 runtime bundle。先确认
  consumer 与最小动作，再决定 automation Secret 和 deploy identity。
- `rds-ca-trust`：backend 镜像已包含 `/app/certs/rds-global-bundle.pem`，生产
  `verify-full` 切换前需要把 `POSTGRES_SSL_ROOT_CERT_FILE` 指向该路径。
- `human-admin-key-hardening`：保留 break-glass 能力，同时让日常人工操作转向
  SSO / short-lived role。

## 公开记录边界

本工作项只记录可公开的架构、迁移顺序和安全约束。实际 principal、resource ID、
token 状态、有效期和应急入口保存在仓库外的私有运维清单中。任何 secret value、
AccessKeyId、token ID 或 credential material 都不得写入 `work-items/`。
