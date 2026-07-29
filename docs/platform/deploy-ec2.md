# EC2 手动部署说明

本文档定义 Dewflow 在 **单台 EC2** 上的手动部署入口，目标是先把人工部署流程标准化，后续再让 GitHub Actions / SSM 复用同一套命令实现自动 CD。

**首次部署**：按可打勾清单执行 [deploy/CHECKLIST.md](../../deploy/CHECKLIST.md)。Tunnel 模板见 [deploy/cloudflare/README.md](../../deploy/cloudflare/README.md)；域名三根线见 [deploy/domains.env.example](../../deploy/domains.env.example)。EC2 栈可用 `make deploy-bootstrap-prod ARGS=ec2-stack` 编排。

## 适用范围

本流程面向：

- 单台 EC2
- Docker Engine + Docker Compose plugin
- 使用 [deploy/docker-compose.yml](../../deploy/docker-compose.yml) 作为正式部署入口
- 使用 RDS 或其它外部 PostgreSQL 作为生产数据库
- 使用 [docker-compose.db.yml](../../docker-compose.db.yml) 继续承担本地 / CI smoke 与测试环境职责

## 部署结构

EC2 默认部署栈包含：

- `redis-cache`
- `redis-taskiq`（`noeviction` + AOF + 持久卷）
- `db_migrator`
- `api`
- `api-nginx`
- `task_worker`

其中：

- `api` / `db_migrator` / `task_worker` 共享同一套后端运行时配置。
- cache 与 TaskIQ broker/result 使用不同 Redis 容器；前者允许 `allkeys-lru`，后者通过 `TASKIQ_RESULT_TTL_SECONDS` 有界保留结果。
- `POSTGRES_SERVER` 指向 RDS / 外部 PostgreSQL；默认 compose 不再启动自管 Postgres。
- `STORAGE_BACKEND=s3` 时，优先让 boto3 走 **EC2 instance profile / 默认 credential chain**，不要在部署文件中长期写死 AWS AK/SK。
- `deploy/docker-compose.yml` 不支持 `STORAGE_BACKEND=local`；local storage 只用于 `docker-compose.db.yml` 的本地 / CI smoke 场景。
- 后端容器使用镜像内置非 root 用户 `appuser`(UID/GID `10001`)；正式 deploy 不再通过 `CURRENT_UID` / `CURRENT_GID` 对齐宿主用户。
- `api-nginx` 是 EC2 本机 API edge，默认只绑定 `127.0.0.1:8081`，供 Cloudflare Tunnel 或本机部署验证访问。
- `frontend` 容器不再默认启动；它只在 `DEPLOY_ENABLE_FRONTEND_FALLBACK=true` 时作为本地演练、回滚预案或自托管 fallback 使用。

如果确实需要单机自管 PostgreSQL，显式叠加 [deploy/docker-compose.local-postgres.yml](../../deploy/docker-compose.local-postgres.yml)。该形态不是推荐生产默认值，必须自行负责备份、恢复演练和磁盘告警。

## 前端上线拓扑（Cloudflare Pages + 独立 API）

当前推荐的上线形态是：

- Frontend：`https://app.<domain>`（Cloudflare Pages）
- API：`https://api.<domain>`（AWS / 自托管入口）
- API 对外路径保持 `/api/v1/...`
- Cloudflare Tunnel：指向 EC2 本机 `http://127.0.0.1:8081`

职责分工：

- **Cloudflare Pages / Cloudflare edge** 负责：
  - 前端静态资源托管
  - TLS / HTTPS
  - 域名接入
  - SPA fallback（通过 `_redirects`）
  - 基础安全头与静态缓存（通过 `_headers`）
- **AWS / 自托管 API 入口** 负责：
  - `https://api.<domain>/api/v1/...` 暴露
  - streaming / SSE 兼容
  - 长 timeout 与 anti-buffering 策略
  - API request tracing / 访问日志
  - 将 `CF-Connecting-IP` 规范化为后端可信的 `X-Real-IP`
- **仓库中的 `frontend/apps/admin/nginx.conf`** 仅继续服务：
  - 本地 Compose 验证
  - 生产镜像演练
  - Pages 回滚时的容器前端 fallback

这意味着 Pages 正式启用后，不应再把 `frontend` 容器当成默认公网入口，也不应再假设前端通过同源 `/api/` 反代后端。

Cloudflare Tunnel 本身暂不纳入 Compose，也不提交 token。生产主机上应将 Tunnel 的 public hostname（如 `api.<domain>`）指向 `http://127.0.0.1:8081`；Cloudflare credential / token 只保存在目标主机或 Cloudflare 托管配置中。`api-nginx` 只能允许 Cloudflare Tunnel / 本机访问，默认 `API_NGINX_BIND=127.0.0.1` 就是这个安全边界；不要把它直接绑定到 `0.0.0.0` 或公网 / 私网入口，否则客户端可以伪造 `CF-Connecting-IP`，绕过按 IP 的认证限流。

Cloudflare Pages 推荐使用 GitHub 集成。Dashboard 配置以下面这份清单为 source of truth：在 Dashboard 改了任何一项，必须回写本清单。

```text
Production branch: main
Root directory: frontend
Build command: pnpm install --frozen-lockfile && pnpm --filter admin build
Build output: apps/admin/dist
Environment (Production): VITE_API_BASE_URL=https://api.<domain>
Environment (Preview): VITE_API_BASE_URL=<生产 API 或独立 staging API；缺失时 CF_PAGES=1 构建会直接失败>
Preview 若指向生产 API，须把 Preview origin 一并写入 BACKEND_CORS_ORIGINS（见 deploy/CHECKLIST.md Phase 4）。
```

版本钉住不依赖 Dashboard 配置：Node 版本由 `frontend/.nvmrc` 决定（当前 22），pnpm 版本由 `frontend/package.json` 的 `packageManager` 字段决定（corepack）。CI 与 Pages 构建读取同一来源，避免环境漂移。唯一例外是 fallback 镜像：`frontend/apps/admin/Dockerfile` 通过 `corepack prepare` 单独钉住相同的 pnpm 版本，升级 `packageManager` 时必须同步修改该行。

### main 分支保护是 Pages 部署的前提

Pages GitHub 集成在 push 到 production branch 时**立即**构建部署，与 GitHub CI 并行——CI 失败不会阻止 Pages 发布。因此部署 gate 必须前移到合并时：

1. GitHub → Settings → Branches → 为 `main` 添加 branch protection rule（或 ruleset）。
2. 勾选 "Require status checks to pass"，required checks 至少包含（与 [scripts/ci/required_status_checks.txt](../../scripts/ci/required_status_checks.txt) 同源）：
   - `Backend static`
   - `Frontend static`
   - `Public content safety`
   - `PR gate`
   - `Frontend e2e smoke (real backend)`
   - `Docker smoke`
3. 勾选 "Require a pull request before merging"，禁止直接 push `main`。

可用脚本一次性写入 secrets 并（可选）应用 branch protection：

```bash
# 需已安装并登录 gh；Pages 变量在知道公网域名后再传：
# BOOTSTRAP_DEPLOY_FRONTEND_BASE_URL=... BOOTSTRAP_DEPLOY_BASE_URL=... \
bash scripts/ci/bootstrap_github_gate.sh
APPLY_BRANCH_PROTECTION=true bash scripts/ci/bootstrap_github_gate.sh
```

另需在仓库 Secrets 手动配置 `BRANCH_PROTECTION_READ_TOKEN`（fine-grained PAT，Administration:Read），供 `guard-branch-protection` 每周审计。详见 [ci-test-matrix.md](../workflows/ci-test-matrix.md) §6。

未配置以上规则时，任何直接 push 到 `main` 的代码都会在 CI 结果出来之前发布到生产 Pages。

### 上线后验证

Pages 部署完成后，从任意机器运行发布检查（脚本化了 CORS、CSP header、telemetry / CSP report origin 守卫等检查项）：

```bash
make verify-pages \
  DEPLOY_FRONTEND_BASE_URL=https://app.<domain> \
  DEPLOY_BASE_URL=https://api.<domain>
```

## 前置条件

在 EC2 上部署前，建议先准备好：

1. 已安装 Docker Engine
2. 已安装 Docker Compose plugin
3. 如果要在部署机本地执行 smoke 验证，已准备 Python / uv 开发环境
4. 已拉取或可访问的业务镜像
5. 已准备 S3 bucket（如果使用 S3 存储）
6. 已准备安全组 / 域名 / 反向代理入口策略
7. 如果使用真实 AWS S3，优先给 EC2 绑定合适的 IAM Role

## 配置文件

部署使用的环境变量模板位于：

- [deploy/.env.ec2.template](../../deploy/.env.ec2.template)

推荐做法：

```bash
cp deploy/.env.ec2.template deploy/.env.ec2
```

然后根据实际环境填写：

- 镜像地址 / tag
- `POSTGRES_*`
- `REDIS_*`
- `S3_BUCKET`
- `LLM_PROVIDER` / `RAG_EMBED_PROVIDER`
- `DEPLOY_BASE_URL`
- `DEPLOY_FRONTEND_BASE_URL`
- `DEPLOY_ENABLE_FRONTEND_FALLBACK`
- `DEPLOY_CHECK_FRONTEND_HEALTH`
- `DEPLOY_PULL_IMAGES`
- `BACKEND_CORS_ORIGINS`
- `RATE_LIMIT_TRUSTED_PROXY_CIDRS`

如果当前版本暂不开放 Google 登录，保持 `GOOGLE_OAUTH_ENABLED=false` 即可；后续启用时再补 `GOOGLE_CLIENT_ID`、`GOOGLE_ALLOWED_REDIRECT_URIS` 和 `secrets/ec2/google_client_secret.txt`。

### 登录限流与真实客户端 IP

认证入口限流按 `client IP + path` 计数。正式 EC2 路径由 `api-nginx` 代理 `/api/`，并把 Cloudflare Tunnel 提供的 `CF-Connecting-IP` 规范化写入 `X-Real-IP`；API 只有在请求来源 IP 命中 `RATE_LIMIT_TRUSTED_PROXY_CIDRS` 时才会读取这个 header。生产 compose 的 Uvicorn command 不启用 `--proxy-headers` / `--forwarded-allow-ips "*"`，避免在应用层校验前就信任客户端可伪造的 forwarded headers。

在 EC2 compose 默认路径中，`api-nginx` 通过专用 `edge_net` 连接 API，并使用固定地址。推荐保留模板里的：

```bash
EDGE_NETWORK_SUBNET=172.30.0.0/24
API_NGINX_BIND=127.0.0.1
API_NGINX_PORT=8081
API_NGINX_PROXY_IP=172.30.0.11
RATE_LIMIT_TRUSTED_PROXY_CIDRS=172.30.0.11/32
```

这只信任 compose `api-nginx` 的固定地址，让 `/sms/login`、`/google/callback` 和 audit 使用真实用户 IP，而不是共享代理 IP。若该 subnet 与宿主机网络冲突，应同时调整 `EDGE_NETWORK_SUBNET`、`API_NGINX_PROXY_IP` 和对应 `/32` CIDR。

`API_NGINX_BIND` 必须保持为本机 loopback 或其他仅允许受信任 edge 访问的地址。只有在前置代理已经校验并规范化真实客户端地址时，才能让 `api-nginx` 读取 `CF-Connecting-IP` 并写入 `X-Real-IP`；直接对公网暴露 `api-nginx` 会让任意客户端伪造 `CF-Connecting-IP`。

如果 API 直接暴露到公网，`RATE_LIMIT_TRUSTED_PROXY_CIDRS` 应保持为空。若改由 Cloudflare、ALB 或其他外部 edge 代理，edge 必须把经过自身校验的客户端地址规范化写入 `X-Real-IP`，并把 `RATE_LIMIT_TRUSTED_PROXY_CIDRS` 改为实际可信代理网段；当前应用不会从 `X-Forwarded-For` 或 `CF-Connecting-IP` 推断客户端地址。请通过 `make deploy-ec2-*` 或等价的 `docker compose --env-file deploy/.env.ec2 ...` 入口启动。

如果前端已经部署到 Cloudflare Pages，至少要同步以下配置：

- `DEPLOY_BASE_URL=https://api.<domain>`
- `DEPLOY_FRONTEND_BASE_URL=https://app.<domain>`
- `BACKEND_CORS_ORIGINS=https://app.<domain>`（Preview 也打生产 API 时，必须把实际 `pages.dev` 等 Preview origin 一并加入；仅 Production 联调则只保留生产前端域名，详见 [deploy/CHECKLIST.md](../../deploy/CHECKLIST.md) Phase 4）
- `GOOGLE_ALLOWED_REDIRECT_URIS=https://app.<domain>/auth/google/callback`（仅在启用 Google OAuth 时）

如果需要临时启用前端容器 fallback：

```bash
DEPLOY_ENABLE_FRONTEND_FALLBACK=true
DEPLOY_CHECK_FRONTEND_HEALTH=true
DEPLOY_FRONTEND_BASE_URL=http://localhost:8080
FRONTEND_PUBLIC_PORT=8080
```

如果回滚到 frontend 容器作为入口，且浏览器经 frontend 容器的同源 `/api/` 反代访问后端，还需要把 `FRONTEND_PROXY_IP` 一并加入可信代理，例如 `RATE_LIMIT_TRUSTED_PROXY_CIDRS=172.30.0.11/32,172.30.0.10/32`，否则后端会忽略 frontend 写入的 `X-Real-IP`，认证限流会退化为按 frontend 容器共享 IP 计数。

> 说明：如果在 EC2 本机执行 API 验证，`DEPLOY_BASE_URL=http://127.0.0.1:8081` 即可；如果希望验证公网域名，也可以改成真实 `https://api.<domain>`。
>
> `make deploy-ec2-*` 会自动把真实 deploy env 文件路径注入给 compose；只有在你把 deploy env 文件移到其他位置时，才需要通过 `DEPLOY_ENV_FILE=...` 覆盖默认路径。`DEPLOY_*` 控制项和镜像名可以用临时 shell 环境变量覆盖；secret 值应写入 EC2 专用 secret 文件，不写进 `deploy/.env.ec2`。
>
> 当前端已经切到 Cloudflare Pages 时，`DEPLOY_BASE_URL` 应理解为 **API 验证入口**，`DEPLOY_FRONTEND_BASE_URL` 才是前端 Pages 站点入口。二者可以不同域名。

## Secret 文件

EC2 部署保持“单目录 + 固定文件名”的 runtime contract。上游可以是人工文件，
也可以是 AWS Secrets Manager；`deploy/.env.ec2` 只保存非敏感的来源、路径和
Secret ID。

### 文件来源（回退路径）

首次部署或需要显式回退时使用：

```bash
make deploy-ec2-secrets-prepare
```

这个步骤会：

- 为 `SECRET_KEY` / `POSTGRES_PASSWORD` / `REDIS_PASSWORD` 生成缺失的随机 secret 文件。
- 为可选集成 secret 创建空文件，后续只需要填启用 provider 所需的文件。
- 保留已有非空 secret，不会覆盖。
- 将 secret 目录设为 `0700`，并将 secret 文件设为容器内 UID `10001` 可读；如果手工改过权限，重新运行该命令。

真实 secret 文件不会提交到 Git。

对应配置：

```dotenv
DEPLOY_SECRET_SOURCE=files
DEPLOY_SECRET_DIR=secrets/ec2
```

### AWS Secrets Manager 来源

生产 runtime bundle 使用 `dewflow-prod-runtime`。JSON key 与现有文件 basename
一一对应，例如 `postgres_password` materialize 为
`postgres_password.txt`。完整 allowlist 见
[`deploy/runtime-secret-manifest.json`](../../deploy/runtime-secret-manifest.json)。

先检查目录并 dry-run 导入；以下命令只打印 key name 和状态，不打印 value：

```bash
make deploy-secrets-status
make deploy-secrets-aws-status
make deploy-secrets-import \
  ARGS="--ssm-override postgres_password=/dewflow/prod/postgres_password"
```

确认后才显式增加 `--apply`。如果目标 Secret 已存在，命令默认拒绝覆盖；
`--update-existing` 只合并传入的非空 key，不删除已有 key。

EC2 使用 instance role 读取明确授权的 runtime Secret。部署配置切换为：

```dotenv
DEPLOY_SECRET_SOURCE=aws
DEPLOY_SECRET_DIR=/run/dewflow-secrets
DEPLOY_RUNTIME_SECRET_ID=dewflow-prod-runtime
DEPLOY_AWS_REGION=us-west-2
```

然后运行：

```bash
make deploy-secrets-materialize
make deploy-ec2-check
```

materialize 会校验 JSON allowlist 和三个必需项，生成全部 24 个兼容文件，将目录
设为 `0700`、文件设为 `0644`，并拒绝替换非本工具管理的非空目录。应用与 Compose
仍只读取 `/run/secrets/*`，不会直接调用 Secrets Manager。

迁移验证完成前保留 `secrets/ec2` 和现有 SSM 参数。尤其是数据库密码，只能在
RDS 真实连接验证后确定权威来源；不要因为导入成功就删除旧值。

> 各 key 对应哪个功能、缺失或上游故障时如何告警与降级，见 [api-keys-and-degradation.md](api-keys-and-degradation.md)。

## 镜像版本与回退

本项目有三个相互独立、不应合并成同一个数字的版本维度：

| 维度 | 取值示例 | 单一来源 | 何时变 |
| --- | --- | --- | --- |
| API 契约版本 | `/api/v1/...` | `configs/app/base.yaml`（`API_ROOT_PATH` + `API_V1_STR`） | 仅破坏性 API 变更 |
| 应用语义版本 | `VERSION=2.0.0` | `configs/app/base.yaml`，打进镜像；喂给 OpenAPI 与 OTel `service.version` | 手动按 semver bump |
| 部署制品标识 | `v2.1.0` / 12 位 git SHA | git tag + 镜像 tag | 每次构建唯一、不可变 |

`VERSION` 不随发布自动递增，也不能跟 git SHA 走（否则 OTel `service.version` 维度基数爆炸）。生产发布和回退以**镜像 tag** 为准：`deploy/.env.ec2` 中的 `DOCKER_IMAGE_NAME_WEB` / `DOCKER_IMAGE_NAME_AI` / `DOCKER_IMAGE_NAME_FRONTEND` 是当前 active image 记录，三者**必须显式设置**——留空或缺失会让 `make deploy-ec2-check` 直接失败（不再有 `2.0.0` 兜底）。

后端 release 镜像使用不可变 git-describe tag，而不是重复覆盖 `2.0.0-web` / `2.0.0-ai`：

```bash
# Release target 会拒绝 tracked 或 untracked 的工作区变更。
export IMAGE_TAG="$(git describe --tags --always --abbrev=12)"

# 本地或 CI 构建后端 web / worker release 镜像
make image-build-release

# 如果使用镜像仓库，先指定仓库名再构建 / push
BACKEND_IMAGE_REPOSITORY=<registry>/dewflow-backend make image-build-release
docker push <registry>/dewflow-backend:${IMAGE_TAG}-web
docker push <registry>/dewflow-backend:${IMAGE_TAG}-ai
```

查看本次发布应写入 `deploy/.env.ec2` 的镜像变量：

```bash
BACKEND_IMAGE_REPOSITORY=<registry>/dewflow-backend \
FRONTEND_IMAGE_REPOSITORY=<registry>/dewflow-frontend \
make release-image-env IMAGE_TAG=${IMAGE_TAG}
```

前端正式发布由 Cloudflare Pages 记录 git commit / deployment history；`DOCKER_IMAGE_NAME_FRONTEND` 只用于 `frontend-fallback` 容器。只有需要构建 fallback 镜像时才运行：

```bash
FRONTEND_IMAGE_REPOSITORY=<registry>/dewflow-frontend make frontend-image-build-release
docker push <registry>/dewflow-frontend:${IMAGE_TAG}
```

### 语义版本 bump（按需）

只有对外语义版本变化时才 bump `VERSION`（功能里程碑 / 正式版本号变更）；日常发布只动镜像 tag，不用碰 `VERSION`。

1. 编辑 `configs/app/base.yaml` 的 `VERSION`（如 `2.0.0` → `2.1.0`），提交。
2. 打 annotated git tag：

   ```bash
   make release-tag          # 读取 base.yaml 的 VERSION，打 v<VERSION> 并提示 push
   git push origin v2.1.0
   ```

3. 之后构建的 release 镜像 `IMAGE_TAG` 会自动带上语义版本（`v2.1.0` / `v2.1.0-3-g<sha>`），无需手填。

### 后端升级流程

1. 在发布记录中保存当前 active image：

   ```bash
   grep '^DOCKER_IMAGE_NAME_' deploy/.env.ec2
   ```

2. 将 `deploy/.env.ec2` 中的 `DOCKER_IMAGE_NAME_WEB` / `DOCKER_IMAGE_NAME_AI` 改成新 tag。
3. 如果镜像需要从 registry 拉取，设置 `DEPLOY_PULL_IMAGES=true`。
4. 执行：

   ```bash
   make deploy-ec2-check
   make deploy-ec2-up
   make deploy-ec2-wait
   make deploy-ec2-verify
   ```

### 后端回退流程

1. 将 `deploy/.env.ec2` 中的 `DOCKER_IMAGE_NAME_WEB` / `DOCKER_IMAGE_NAME_AI` 恢复到上一组已验证 tag。
2. 保持 `DEPLOY_PULL_IMAGES=true`，确保目标主机拉取旧镜像。
3. 执行：

   ```bash
   make deploy-ec2-up
   make deploy-ec2-wait
   make deploy-ec2-verify
   ```

如果本次发布包含数据库 migration，先确认 migration 是否向后兼容。不可逆或破坏性 schema 变更不能只靠镜像回退修复；需要按 [RDS 备份与恢复](rds-backup-and-restore.md) 中的流程使用 snapshot / PITR，或执行明确的反向迁移。

### 数据库配置

生产默认使用 RDS / 外部 PostgreSQL。`deploy/.env.ec2` 中保持：

```dotenv
POSTGRES_SERVER=<rds-endpoint>
POSTGRES_PORT=5432
POSTGRES_SSL_MODE=verify-full
# Dewflow backend 镜像内置公开的 AWS RDS global CA bundle。
POSTGRES_SSL_ROOT_CERT_FILE=/app/certs/rds-global-bundle.pem
```

数据库密码仍写入 `secrets/ec2/postgres_password.txt`，不要写进 `.env.ec2`。`verify-full` 会校验服务端证书与 RDS endpoint 主机名，因此 `POSTGRES_SERVER` 必须填写 RDS 控制台给出的 endpoint 主机名（例如 `xxx.amazonaws.com`），**不要**填写 IP 地址；`make deploy-ec2-check` 会在 `verify-ca` / `verify-full` 下拦截 IPv4 字面量。RDS security group 需要允许 EC2 实例访问 5432；RDS backup retention / snapshot / PITR 策略在 AWS 侧配置和演练。

低成本自管 fallback 才使用 compose 内置 Postgres：

```dotenv
POSTGRES_SERVER=postgres
POSTGRES_SSL_MODE=disable
DEPLOY_EXTRA_COMPOSE_FILES=deploy/docker-compose.local-postgres.yml
```

该 override 会创建 `prod_db_volume` 并恢复 `postgres` healthcheck 依赖；删除卷或迁移到 RDS 前必须先完成备份。

### 存储配置

EC2 deploy 栈只支持 S3-compatible object storage：

```dotenv
STORAGE_BACKEND=s3
S3_BUCKET=<bucket-name>
S3_PREFIX=knowledge_files
S3_REGION=<aws-region>
```

`make deploy-ec2-check` 会拒绝 `STORAGE_BACKEND=local`。如果需要验证本地文件存储，请使用 [docker-compose.db.yml](../../docker-compose.db.yml) 的本地 / CI smoke 栈，不要在正式 deploy 栈补 `knowledge_storage_init`。

### 前端回退流程

Cloudflare Pages 前端优先在 Cloudflare Dashboard 回退到上一条成功 deployment。只有 Pages 故障或需要自托管临时入口时，才启用 `frontend-fallback` profile，并把 `DOCKER_IMAGE_NAME_FRONTEND` 指向已验证的 fallback 镜像 tag。

## Makefile 入口

手动部署统一通过根目录 [Makefile](../../Makefile) 暴露以下命令：

- `make deploy-ec2-check`
- `make deploy-ec2-secrets-prepare`
- `make deploy-ec2-up`
- `make deploy-ec2-wait`
- `make deploy-ec2-verify`
- `make deploy-ec2-logs`
- `make deploy-ec2-down`
- `make deploy-cloudwatch-setup`

这些命令底层调用：

- `scripts/deploy/ec2-check.sh`
- `scripts/deploy/ec2-secrets-prepare.sh`
- `scripts/deploy/ec2-up.sh`
- `scripts/deploy/ec2-wait.sh`
- `scripts/deploy/ec2-verify.sh`
- `scripts/deploy/ec2-logs.sh`
- `scripts/deploy/ec2-down.sh`
- `deploy/monitoring/cloudwatch-setup.sh`

## 推荐部署顺序

### 1. 准备 secret 文件

```bash
make deploy-ec2-secrets-prepare
```

如果需要真实 provider key，把对应值写入 `secrets/ec2/*.txt`。

### 2. 创建 / 更新 CloudWatch 日志与告警资源

```bash
make deploy-cloudwatch-setup
```

这个步骤会创建或更新：

- CloudWatch Logs log group
- SNS topic
- 第一批 log metric filters
- CloudWatch alarms

### 3. 预检查

```bash
make deploy-ec2-check
```

这个步骤会检查：

- Docker / Compose 是否可用
- deploy env 文件是否存在
- 关键变量是否已填写
- 必填 secret 文件是否存在、非空且不是占位值
- compose 配置能否成功渲染
- 当服务日志仍使用 `awslogs` 时，AWS CLI 是否可用且 CloudWatch log group 是否已存在

### 4. 启动 / 更新部署栈

```bash
make deploy-ec2-up
```

这个步骤会：

- 在 `DEPLOY_PULL_IMAGES=true` 时拉取镜像
- 启动核心服务
- 打印当前容器状态

### 5. 等待服务 ready

```bash
make deploy-ec2-wait
```

默认会检查：

- API liveness: `${DEPLOY_BASE_URL}${DEPLOY_API_LIVE_PATH}`
- API DB readiness: `${DEPLOY_BASE_URL}${DEPLOY_API_READY_PATH}`

只有在 `DEPLOY_CHECK_FRONTEND_HEALTH=true` 时才会额外检查 frontend health：`${DEPLOY_FRONTEND_BASE_URL}${DEPLOY_FRONTEND_HEALTH_PATH}`。当生产前端已经切到 Cloudflare Pages 时，建议把 `DEPLOY_FRONTEND_HEALTH_PATH` 保持为 `/healthz`，并让 Pages 静态产物提供简单 `healthz` 文件，用于上线探活。

### 6. 跑部署后 smoke 验证

```bash
make deploy-ec2-verify
```

这个步骤会复用现有 smoke 验证框架，但默认只跑更适合远端部署的子集：

- `tests/smoke/test_core_api_flow_smoke.py`
- `tests/smoke/test_chat_http_smoke.py`
- `tests/smoke/test_rag_http_smoke.py`

默认不把 knowledge smoke 作为第一轮 EC2 部署验证必跑项，因为它通常对 DB / storage 假设更深，适合后续逐步放开。

### 7. 查看日志

```bash
make deploy-ec2-logs
```

也可以指定服务名，例如：

```bash
make deploy-ec2-logs ARGS="api"
```

> 如果需要进一步增强，也可以后续把日志 target 改成更显式的服务参数形式。

### 8. 停止部署栈

```bash
make deploy-ec2-down
```

如果要连 volume 一起删除，必须显式设置 `DEPLOY_CONFIRM_VOLUME_WIPE=yes`；无确认时默认保留命名卷。

## RDS 备份与恢复

生产数据库的 snapshot、PITR、发布前检查和恢复演练统一见 [rds-backup-and-restore.md](rds-backup-and-restore.md)。高风险 migration 或不可逆发布必须先完成对应 checklist。

## Bifrost Gateway

[deploy/docker-compose.yml](../../deploy/docker-compose.yml) 保留了 Bifrost gateway 服务，但默认作为 **可选 profile** 关闭。

如果 `LLM_PROVIDER`、`RAG_EMBED_PROVIDER`、`RAG_PLANNER_PROVIDER` 或 `RAG_RERANK_PROVIDER` 使用 `bifrost*` / `gateway-*` provider，部署脚本会自动启用 `bifrost` profile。也可以显式设置：

```bash
export DEPLOY_ENABLE_BIFROST=true
```

启用后，需要确保 `secrets/ec2` 下已写入 Bifrost 自身和下游 provider 所需 key，例如：

- `bifrost_api_key.txt`
- `bifrost_encryption_key.txt`
- `deepseek_api_key.txt` / `deepseek_api_key_2.txt`
- `dashscope_api_key.txt` / `dashscope_api_key_2.txt`
- `cohere_api_key.txt` / `cohere_api_key_2.txt`

## Observability

[deploy/docker-compose.yml](../../deploy/docker-compose.yml) 是 EC2 / AWS 目标态，默认使用 Docker `awslogs` driver 将容器 stdout 写入 CloudWatch Logs。业务层仍输出 JSON 日志，日志字段合同见 [deploy/monitoring/README.md](../../deploy/monitoring/README.md)。

生产告警投递目标：

```text
backend/worker JSON logs -> CloudWatch Logs -> metric filters -> CloudWatch alarms -> SNS topic -> email subscription
```

CloudWatch Logs 变量来自 `deploy/.env.ec2`：

```env
DEPLOY_CW_LOG_GROUP=/dewflow/prod
DEPLOY_AWS_REGION=us-west-2
DEPLOY_CW_LOG_STREAM_PREFIX=dewflow
DEPLOY_CW_METRIC_NAMESPACE=Dewflow/Logs
DEPLOY_ALERTS_SNS_TOPIC_NAME=dewflow-prod-alerts
# DEPLOY_ALERTS_SNS_EMAIL=alerts@example.com
DEPLOY_CW_API_LATENCY_THRESHOLD_MS=2000
DEPLOY_CW_QUEUE_DEPTH_THRESHOLD=100
DEPLOY_CW_OLDEST_PENDING_THRESHOLD_SECONDS=300
```

首次部署前创建或更新 CloudWatch log group、SNS topic、metric filters 和 alarms：

```bash
make deploy-cloudwatch-setup
```

EC2 instance role 至少需要对该 log group 具备：

- `logs:CreateLogStream`
- `logs:DescribeLogStreams`
- `logs:PutLogEvents`

运行 `make deploy-cloudwatch-setup` 的人或 CI role 还需要
`logs:CreateLogGroup`、`logs:DescribeLogGroups`、`logs:PutMetricFilter`、
`cloudwatch:PutMetricAlarm`、`sns:CreateTopic`、`sns:ListSubscriptionsByTopic`；
配置 email 时还需要 `sns:Subscribe`。受控送达验证另需
`logs:DescribeLogStreams`、`logs:CreateLogStream`、`logs:PutLogEvents` 与
`cloudwatch:DescribeAlarms`。

最少告警验证步骤：

1. 运行 `make deploy-cloudwatch-setup`。
2. 确认 `api`、`task_worker` 和 `credit_scheduler` 日志进入同一个 CloudWatch Logs log group。
3. 在 SNS topic 上添加 email / ChatOps subscription；收件人必须完成确认。
4. 确认 API 5xx / latency、queue depth / oldest pending、E2E heartbeat、
   terminal failure、Redis risk、probe failure 与 synthetic delivery filters 已创建。
5. 运行 `make deploy-cloudwatch-verify-delivery`，等待 synthetic Alarm 进入
   `ALARM`，再由 confirmed receiver 明确确认实际收到通知。

查看生产日志：

```bash
aws logs tail "$DEPLOY_CW_LOG_GROUP" \
  --region "$DEPLOY_AWS_REGION" \
  --follow
```

CSP report-only 第一阶段只用于日志观察：`POST /api/v1/csp/reports` 会写 `event=csp_violation`，但不落库、不触发应用告警，也暂不建 CloudWatch alarm。等 report-only 噪声稳定并确认 allowlist 后，再决定是否为 CSP 加 metric filter。

T1-Lite 只从显式 structured event 得到 API `duration_ms` Maximum、5xx count、
queue / oldest age 与 Redis restart / eviction delta；它们不能表述为 P99、错误率、
Redis memory capacity 或完整 SLO。后续分布指标、托管 RDS / ElastiCache 指标仍需
EMF、ADOT / CloudWatch exporter、AMP 或 AWS managed metrics。迁移清单见
[deploy/monitoring/alarms-cloudwatch.md](../../deploy/monitoring/alarms-cloudwatch.md)。

## 与本地 smoke 的边界

请保持以下职责分离：

- [deploy/docker-compose.yml](../../deploy/docker-compose.yml) → **EC2 / 正式部署入口**
- [deploy/docker-compose.local-postgres.yml](../../deploy/docker-compose.local-postgres.yml) → **可选自管 PostgreSQL fallback**
- [deploy/docker-compose.local-s3.yml](../../deploy/docker-compose.local-s3.yml) → **本地生产形态演练，使用 MinIO 模拟 S3**
- [deploy/docker-compose.local-logging.yml](../../deploy/docker-compose.local-logging.yml) → **本地生产形态演练，把 awslogs 降级为 json-file**
- [docker-compose.db.yml](../../docker-compose.db.yml) → **本地 / CI smoke 和测试环境**（包含 `otel-collector` 等 smoke-only 组件）

不要把两者重新揉成一套，否则会让部署面和测试面相互污染。

## 基础设施镜像维护

当前钉版、同步修改位置和季度核查步骤见 [infrastructure-image-maintenance.md](infrastructure-image-maintenance.md)。镜像升级仍按普通 deploy 变更运行 `make deploy-ec2-check`。

## 本地生产形态演练

生产 compose、secret 注入、frontend fallback、worker、migration 和 S3 的本地验证步骤见 [local-production-rehearsal.md](local-production-rehearsal.md)。

## 后续自动 CD 的接入方式

未来如果接 GitHub Actions / SSM，推荐复用现有手动入口，而不是重写一套部署逻辑。

理想做法是：

1. CI 负责 build / push images
2. SSM 或远程执行负责调用：
   - `make deploy-secrets-materialize`（`DEPLOY_SECRET_SOURCE=aws`）
   - `make deploy-ec2-check`
   - `make deploy-ec2-up`
   - `make deploy-ec2-wait`
   - `make deploy-ec2-verify`
3. 失败时通过 `make deploy-ec2-logs` 收集排障信息

也就是说：

> 自动 CD 应该只是“替你执行已经稳定的人工部署流程”，而不是重新发明第二套流程。
