# 后端 CD 流水线与生产环境构建

本文档记录 Dewflow 后端**自动化交付链路**的设计、生产环境的**一次性构建过程**，以及首次上线时暴露的问题与修复。

- 手动部署命令语义见 [deploy-ec2.md](deploy-ec2.md)（CD 复用同一套 `make deploy-ec2-*`）
- 首次部署的可打勾清单见 [deploy/CHECKLIST.md](../../deploy/CHECKLIST.md)
- 前端边缘职责见 [frontend-delivery-and-edge-responsibilities.md](frontend-delivery-and-edge-responsibilities.md)

> 本文所有资源标识（账号 ID、实例 ID、RDS endpoint、bucket、tunnel ID 等）一律使用占位符。真实值存放在 GitHub repo variables 与 AWS SSM 参数库，不写入仓库。

## 1. 拓扑总览

```text
开发者 ──push tag v*──► GitHub Actions
                          │  ① build-push（OIDC → 临时凭证）
                          │     make image-build-release → docker push
                          ▼
                        ECR（immutable tag）
                          │
                          │  ② deploy（production environment 审批闸门）
                          │     aws ssm send-command
                          ▼
                     SSM 服务 ──agent 出站轮询──► EC2
                                                  │ git checkout <tag>
                                                  │ ec2-remote-deploy.sh
                                                  │   → make deploy-ec2-check
                                                  │   → deploy-ec2-up（含 db_migrator）
                                                  │   → deploy-ec2-wait / verify
                                                  ▼
                                            last-good-tag 落盘

浏览器 ──► Cloudflare Access 门禁 ──► Pages（前端静态资源）
       └─► api.<domain> ──Tunnel──► EC2 api-nginx → api → worker
                                          └─► RDS / S3 / Redis
```

关键性质：

- **GitHub 侧零长期云凭证**：仅 OIDC 换取的 1 小时临时凭证。
- **EC2 零入站端口**：安全组无 inbound 规则，无 SSH 密钥对，全部管理动作走 SSM（agent 主动出站）。
- **镜像不可变**：ECR 仓库开启 `IMMUTABLE` tag，部署对象永远是一个确定的 tag。

## 2. CD 流水线

实现文件：[.github/workflows/deploy-backend.yml](../../.github/workflows/deploy-backend.yml)、[scripts/deploy/ec2-remote-deploy.sh](../../scripts/deploy/ec2-remote-deploy.sh)。

### 2.1 触发方式

| 触发 | 行为 |
| --- | --- |
| `push` tag `v*` | 构建该 tag 的镜像并部署 |
| `workflow_dispatch`（不填 `image_tag`） | 构建当前 ref 并部署 |
| `workflow_dispatch`（填 `image_tag`） | **跳过构建**，直接部署 ECR 中已存在的镜像（回滚 / 重部路径） |

`concurrency: deploy-backend-production` + `cancel-in-progress: false` 保证同一时刻只有一次生产部署在跑，且不会被后来的 run 打断。

### 2.2 build-push job

1. `actions/checkout` 使用 `fetch-depth: 0`（`git describe` 需要完整历史）。
2. 镜像 tag 取 `git describe --tags --always --abbrev=12`，与仓库既有 release 约定一致。
3. `aws-actions/configure-aws-credentials` 以 `vars.DEPLOY_ROLE_ARN` 换取临时凭证。
4. 复用 `make image-build-release`，仅覆盖 `BACKEND_IMAGE_REPOSITORY` 指向 ECR，**不新增构建逻辑**。
5. 推送 `<repo>:<tag>-web` 与 `<repo>:<tag>-ai`。

### 2.3 deploy job

- `environment: production` —— 审批闸门。配置了 required reviewer 时，job 会停在 `waiting` 等待人工 approve；把 reviewer 移除即变为全自动，无需改动 workflow。
- `if: always() && (needs.build-push.result == 'success' || 'skipped')` —— 让「跳过构建的回滚路径」也能进入部署。
- 通过 `aws ssm send-command` 下发远端脚本，轮询 `get-command-invocation` 直到终态，回传 stdout；失败时额外打印 stderr 并让 job 失败。
- 输出同时写入 CloudWatch 日志组 `/dewflow/ssm`，便于事后追溯。

### 2.4 远端脚本（EC2 上执行）

`scripts/deploy/ec2-remote-deploy.sh <image-tag>` 的职责：

1. `aws ecr get-login-password | docker login`（走实例角色，主机上无静态凭证）。
2. 将 `DOCKER_IMAGE_NAME_WEB/AI` 写入 `deploy/.env.ec2`。
3. `make deploy-ec2-check`：env 与 compose 的前置校验（必填项、占位符、secret 文件权限、CloudWatch 日志组存在性等）。
4. `DEPLOY_PULL_IMAGES=true make deploy-ec2-up`：拉取并启动。数据库迁移由 compose 中的 `db_migrator` 服务完成，`api` 通过 `depends_on: service_completed_successfully` 等待其成功，**迁移与启动的顺序由 compose 保证，脚本不额外编排**。
5. `make deploy-ec2-wait` / `make deploy-ec2-verify`：健康端点等待 + smoke 校验。
6. 成功后写入 `/opt/dewflow/last-good-tag`。

### 2.5 回滚

回滚不是独立系统，就是「用旧 tag 再跑一次同一条流水线」：

```bash
gh workflow run deploy-backend.yml --ref main -f image_tag=<上一个正常的 tag>
```

因为镜像不可变且 `image_tag` 存在时跳过构建，这条路径既快又确定。当前 verify 失败**只让流水线失败并告警，不自动回滚**——自动回滚待链路运行稳定后再引入。

## 3. AWS 基础设施

单 region（本次为 `us-west-2`），全部资源在默认 VPC 内。

### 3.1 资源清单

| 资源 | 配置要点 |
| --- | --- |
| ECR ×2（backend / frontend） | `IMMUTABLE` tag、`scanOnPush` |
| EC2 ×1 | Ubuntu 24.04、gp3 30GB、**IMDSv2 required**、无密钥对 |
| 安全组 `*-ec2-sg` | **无 inbound 规则** |
| 安全组 `*-rds-sg` | 仅允许来源为 ec2-sg 的 5432 |
| RDS PostgreSQL | 单 AZ、`--no-publicly-accessible`、存储加密、私有子网组 |
| S3 | 全部 public access block 开启 |
| CloudWatch 日志组 | `/dewflow/prod`（容器 awslogs）、`/dewflow/ssm`（部署输出），保留 30 天 |
| SSM 参数库 | `SecureString`：数据库密码、tunnel token、bootstrap 账号密码 |
| Budgets | 月度预算 + 50%/80% 实际、100% 预测三档邮件告警 |
| Cost Anomaly Detection | 单日异常消费超阈值即邮件 |

### 3.2 IAM 权限模型

**`dewflow-gha-deploy`（GitHub Actions 假借的角色）**

- 信任策略：OIDC provider `token.actions.githubusercontent.com`，`aud = sts.amazonaws.com`，`sub` 限定 `repo:<owner>/<repo>:*`。
- 权限仅三类：`ecr:GetAuthorizationToken`；对两个 ECR 仓库的 push/pull；对**指定实例**的 `ssm:SendCommand` + 读取执行结果。
- 不具备创建资源、读取 secret、访问数据库的能力。CI 被攻破的最坏后果是「部署了一个坏版本」，而坏版本可回滚。

**`dewflow-ec2-role`（实例角色）**

- `AmazonSSMManagedInstanceCore`（被管理）、`AmazonEC2ContainerRegistryReadOnly`（拉镜像）、`CloudWatchAgentServerPolicy`（写日志）。
- 内联：`ssm:GetParameter` 限定 `/dewflow/*`；单个 S3 bucket 的读写。
- 应用因此**不需要任何 S3 access key**，`S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` 保持为空即可。

## 4. EC2 主机一次性配置

以下动作全部通过 `aws ssm send-command` 完成，未使用 SSH。

1. **基础组件**：`docker`（官方安装脚本）、`make`、`jq`、`aws-cli`、`uv`。
2. **仓库副本**：生成 ed25519 密钥并注册为 GitHub **read-only deploy key**，clone 到 `/opt/dewflow/repo`。主机因此只能读代码，无法推送。
3. **部署 env**：从 `deploy/.env.ec2.template` 生成 `deploy/.env.ec2`，按本机实际填写：
   - `POSTGRES_SERVER` = RDS endpoint（**必须是主机名**，`verify-full` 会校验证书 CN/SAN）
   - `POSTGRES_SSL_MODE=verify-full`、`POSTGRES_SSL_ROOT_CERT_FILE=/app/certs/rds-global-bundle.pem`
   - `S3_BUCKET` / `S3_REGION` / `DEPLOY_AWS_REGION`
   - `BACKEND_CORS_ORIGINS` = 前端所有正式来源
   - `BETA_USER_EMAIL_WHITELIST` = 内测邮箱
4. **secret 文件**：`make deploy-ec2-secrets-prepare` 生成 `secrets/ec2/*.txt`（目录 0700、文件对容器 UID 10001 可读）；数据库密码从 SSM 参数库覆盖写入，保证与 RDS 一致。未启用的集成 secret 保持空文件。
5. **cloudflared**：安装 deb 包，用 SSM 参数库中的 tunnel token 执行 `cloudflared service install`，注册为 systemd 服务。

## 5. Cloudflare 边缘

| 组件 | 配置 |
| --- | --- |
| Tunnel | named tunnel，**remote-managed** ingress；`api.<domain>` → `http://localhost:8081`（compose 的 api-nginx），其余 404 |
| DNS | `api` → `<tunnel-id>.cfargotunnel.com`；`app` / apex / `www` → `<project>.pages.dev`，全部 proxied |
| Pages | direct-upload 项目，production branch `main`，三个自定义域 |
| Access | self-hosted 应用罩住三个前端域名，策略仅允许所有者邮箱（一次性验证码），会话 168h |

要点：

- Tunnel ingress 支持**按路径**匹配，可以在边缘直接拒绝某个 API 路径（本次用于封锁开放注册），不必依赖 WAF 权限。
- **API 域名不在 Access 之后**：前端页面受门禁保护，但浏览器仍需直连 API，因此 API 的防护依赖应用层限流、CORS 与边缘规则。
- 邮件相关的 MX / TXT 记录与前端上线无关，切换 DNS 时不要动。

## 6. 首次上线问题复盘

按发生顺序记录。每一条都是「不做真实生产部署就不会暴露」的问题。

### 6.1 免费套餐限制

- **现象**：`CreateDBInstance` 报 `FreeTierRestrictionError`（备份保留期超限）；`RunInstances` 报实例类型不符合 free tier。
- **处置**：备份保留期临时降到 1 天；实例类型改用 free-tier 允许的规格。
- **教训**：账号计划会静默约束参数取值；升级付费方案后应把备份保留期调回 7 天、并按实际负载选机型。

### 6.2 RDS 保留用户名

- **现象**：`MasterUsername admin cannot be used as it is a reserved word`。
- **处置**：改用非保留名（如 `dewflow_admin`），并同步 `POSTGRES_USER`。

### 6.3 SSM 用 sh 执行 bash 脚本

- **现象**：远端脚本第 1 行即失败：`set: Illegal option -o pipefail`。
- **根因**：`AWS-RunShellScript` 默认以 `sh` 执行，`set -o pipefail` 是 bashism。
- **处置**：把远端脚本包进显式 `bash -c`（用 `jq @sh` 做引号转义）。
- **教训**：所有经 SSM 下发的脚本都不能假定 bash。

### 6.4 `awslogs-stream-prefix` 是 ECS 专属选项

- **现象**：容器创建失败 `unknown log opt 'awslogs-stream-prefix' for awslogs log driver`。
- **根因**：该选项只存在于 ECS 的 awslogs 集成，纯 Docker 的 awslogs driver 不认。
- **处置**：改用原生 `tag` 选项（`'<prefix>/{{.Name}}'`）保持既定的日志流命名。
- **影响面**：`deploy/docker-compose.yml`、`deploy/docker-compose.local-postgres.yml`。

### 6.5 alembic 迁移引擎忽略 SSL 配置

- **现象**：迁移容器退出 1，日志为 `no pg_hba.conf entry for host ..., no encryption`。
- **根因**：`alembic/env.py` 构造 async engine 时未传 `settings.database_connect_args`，导致 `POSTGRES_SSL_MODE` 对迁移路径**完全无效**——运行时引擎是正确的，只有迁移在裸连。
- **处置**：迁移引擎复用运行时同款 `connect_args`。
- **教训**：本地/CI 的 Postgres 不强制 SSL，这个缺陷在遇到 RDS（`rds.force_ssl`）之前无法暴露。**运行时与迁移必须共用同一套连接参数来源**。

### 6.6 RDS 证书链不被系统信任库认可

- **现象**：`ssl.SSLCertVerificationError: certificate verify failed: self-signed certificate in certificate chain`。
- **根因**：asyncpg 按系统 CA 校验，而 RDS 使用 Amazon 自有 CA，不在通用信任库中。
- **处置**：把 AWS 公开的 RDS global CA bundle 烤进镜像的 web / worker 两个 stage（`/app/certs/rds-global-bundle.pem`，公开信任锚、非机密），env 指向它并保持 `verify-full`。
- **备注**：`settings.py` 中 `require` 被映射为 asyncpg 的 `ssl=True`（含完整校验），语义比 libpq 的 `require`（只加密不验证）更严格。当前使用 `verify-full` 绕开该差异，语义对齐留作后续修复项。

### 6.7 主机 aws-cli 的 `--query ... --output text` 静默产出空内容

- **现象**：写入主机的数据库密码文件长度为 0，导致 `password authentication failed`；而同样的命令在开发机上正常。
- **根因**：主机上以 snap 方式安装的 aws-cli 在该用法下输出为空（无报错、退出码 0）。
- **处置**：改用 `aws ssm get-parameter ... | jq -r .Parameter.Value` 提取。
- **教训**：**静默失败最危险**。凡是把命令输出写进 secret 文件的地方，都要立即校验长度/哈希，不能只看退出码。

### 6.8 `workflow_dispatch` 在特性分支上不可用

- **现象**：workflow 尚未合入默认分支时，`gh workflow run` 返回 404。
- **根因**：GitHub 只识别**默认分支上**的 `workflow_dispatch` 定义。
- **处置**：迭代阶段用 tag push 触发；合入 main 后 dispatch（含回滚路径）才可用。

### 6.9 一次性容器无法通过 `*_FILE` 机制取 secret

- **现象**：用 `docker run` 跑 seed 脚本时报 `SECRET_KEY must not use the local default outside local`。
- **根因**：`FOO_FILE` → `FOO` 的加载发生在应用启动流程中，独立脚本不经过该路径。
- **处置**：在主机侧读取 secret 文件内容，通过 `-e` 显式传入。同时把整段远端脚本用 base64 传输，避开 SSM 参数 JSON 的多层引号转义。

### 6.10 `www` 指向 apex 导致 Access 不匹配

- **现象**：Access 应用已包含 `www`，但该域名仍可匿名访问（200，未 302 到登录墙）。
- **根因**：`www` 是指向 apex 的旧 CNAME，与另外两个直连 Pages 的域名结构不一致。
- **处置**：把 `www` 改为与 `app` / apex 一致，直接 CNAME 到 Pages。

### 6.11 注册端点无验证即可创建账号（安全问题）

- **现象**：`POST /api/v1/auth/register` 仅提交 `{"username": "..."}` 即返回 200 并创建 `is_active` 用户，**无密码、无邮箱、无任何验证**。
- **风险**：公网可无限刷号，撑爆数据库；比 LLM 成本更现实的攻击面。
- **临时处置**：Tunnel ingress 增加路径规则，对该路径直接返回 403（边缘拦截，请求不进入 EC2）。
- **待办**：**代码级修复仍未完成**——需要注册开关 / 邀请码 / 真实验证渠道。边缘拦截只是缓解，不是修复。

## 7. 日常操作

### 发布

```bash
git tag -a vX.Y.Z -m "release vX.Y.Z" && git push origin vX.Y.Z
# GitHub Actions 自动构建 → 在 production environment 处等待审批 → 部署
gh run watch <run-id>
```

### 回滚

```bash
gh workflow run deploy-backend.yml --ref main -f image_tag=<旧 tag>
```

### 排障入口

```bash
aws logs tail /dewflow/prod --since 15m --format short     # 容器日志
aws logs tail /dewflow/ssm  --since 30m --format short     # 部署命令输出
aws ssm send-command --instance-ids <id> --document-name AWS-RunShellScript \
  --parameters 'commands=["docker ps --format \"{{.Names}} {{.Status}}\""]'
```

### 修改主机配置

`deploy/.env.ec2` 与 `secrets/ec2/*` 只存在于主机（不进 git）。改完后**必须重跑一次部署**（`workflow_dispatch` 指定当前 tag）让容器重建生效。

## 8. 已知缺口

| 项 | 说明 |
| --- | --- |
| 注册端点代码级修复 | 当前仅边缘 403 缓解，见 6.11 |
| 前端 CD | Pages 首次发布为本地 wrangler 直传，尚无 CI 工作流 |
| verify 失败自动回滚 | 当前仅失败告警，人工决定回滚 |
| `POSTGRES_SSL_MODE=require` 语义 | 见 6.6 备注 |
| 镜像漏洞扫描接入 CD | ECR `scanOnPush` 已开，尚未在流水线中 gate |
| 免费套餐参数 | 备份保留期、实例规格待升级付费方案后调整 |
