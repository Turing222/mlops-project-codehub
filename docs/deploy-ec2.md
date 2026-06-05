# EC2 手动部署说明

本文档定义 Dewflow 在 **单台 EC2** 上的手动部署入口，目标是先把人工部署流程标准化，后续再让 GitHub Actions / SSM 复用同一套命令实现自动 CD。

## 适用范围

本流程面向：

- 单台 EC2
- Docker Engine + Docker Compose plugin
- 使用 [deploy/docker-compose.yml](../deploy/docker-compose.yml) 作为正式部署入口
- 使用 [docker-compose.db.yml](../docker-compose.db.yml) 继续承担本地 / CI smoke 与测试环境职责

## 部署结构

EC2 默认部署栈包含：

- `postgres`
- `redis`
- `db_migrator`
- `api`
- `frontend`
- `task_worker`

其中：

- `frontend` 是默认公网入口，并继续通过 `/api/` 反向代理后端 API。
- `api` / `db_migrator` / `task_worker` 共享同一套后端运行时配置。
- `STORAGE_BACKEND=s3` 时，优先让 boto3 走 **EC2 instance profile / 默认 credential chain**，不要在部署文件中长期写死 AWS AK/SK。

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

- [deploy/.env.ec2.template](../deploy/.env.ec2.template)

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
- `DEPLOY_PULL_IMAGES`

如果当前版本暂不开放 Google 登录，保持 `GOOGLE_OAUTH_ENABLED=false` 即可；后续启用时再补 `GOOGLE_CLIENT_ID`、`GOOGLE_ALLOWED_REDIRECT_URIS` 和 `secrets/ec2/google_client_secret.txt`。

> 说明：如果在 EC2 本机执行验证，`DEPLOY_BASE_URL=http://localhost` 通常就够了；如果希望验证公网域名，也可以改成真实域名。
>
> `make deploy-ec2-*` 会自动把真实 deploy env 文件路径注入给 compose；只有在你把 deploy env 文件移到其他位置时，才需要通过 `DEPLOY_ENV_FILE=...` 覆盖默认路径。`DEPLOY_*` 控制项和镜像名可以用临时 shell 环境变量覆盖；secret 值应写入 EC2 专用 secret 文件，不写进 `deploy/.env.ec2`。

## Secret 文件

EC2 部署使用 [secrets/ec2](../secrets/ec2) 作为专用 secret 目录，`deploy/.env.ec2` 只保存非敏感配置和 secret 文件路径。

首次部署前运行：

```bash
make deploy-ec2-secrets-prepare
```

这个步骤会：

- 为 `SECRET_KEY` / `POSTGRES_PASSWORD` / `REDIS_PASSWORD` 生成缺失的随机 secret 文件。
- 为可选集成 secret 创建空文件，后续只需要填启用 provider 所需的文件。
- 保留已有非空 secret，不会覆盖。

真实 secret 文件不会提交到 Git。

## Makefile 入口

手动部署统一通过根目录 [Makefile](../Makefile) 暴露以下命令：

- `make deploy-ec2-check`
- `make deploy-ec2-secrets-prepare`
- `make deploy-ec2-up`
- `make deploy-ec2-wait`
- `make deploy-ec2-verify`
- `make deploy-ec2-logs`
- `make deploy-ec2-down`

这些命令底层调用：

- `scripts/deploy/ec2-check.sh`
- `scripts/deploy/ec2-secrets-prepare.sh`
- `scripts/deploy/ec2-up.sh`
- `scripts/deploy/ec2-wait.sh`
- `scripts/deploy/ec2-verify.sh`
- `scripts/deploy/ec2-logs.sh`
- `scripts/deploy/ec2-down.sh`

## 推荐部署顺序

### 1. 准备 secret 文件

```bash
make deploy-ec2-secrets-prepare
```

如果需要真实 provider key，把对应值写入 `secrets/ec2/*.txt`。

### 2. 预检查

```bash
make deploy-ec2-check
```

这个步骤会检查：

- Docker / Compose 是否可用
- deploy env 文件是否存在
- 关键变量是否已填写
- 必填 secret 文件是否存在、非空且不是占位值
- compose 配置能否成功渲染

### 3. 启动 / 更新部署栈

```bash
make deploy-ec2-up
```

这个步骤会：

- 在 `DEPLOY_PULL_IMAGES=true` 时拉取镜像
- 启动核心服务
- 打印当前容器状态

### 4. 等待服务 ready

```bash
make deploy-ec2-wait
```

默认会检查：

- frontend health: `/healthz`
- API liveness: `/api/v1/health_check/live`
- API DB readiness: `/api/v1/health_check/db_ready`

### 5. 跑部署后 smoke 验证

```bash
make deploy-ec2-verify
```

这个步骤会复用现有 smoke 验证框架，但默认只跑更适合远端部署的子集：

- `tests/smoke/test_core_api_flow_smoke.py`
- `tests/smoke/test_chat_http_smoke.py`
- `tests/smoke/test_rag_http_smoke.py`

默认不把 knowledge smoke 作为第一轮 EC2 部署验证必跑项，因为它通常对 DB / storage 假设更深，适合后续逐步放开。

### 6. 查看日志

```bash
make deploy-ec2-logs
```

也可以指定服务名，例如：

```bash
make deploy-ec2-logs ARGS="api"
```

> 如果需要进一步增强，也可以后续把日志 target 改成更显式的服务参数形式。

### 7. 停止部署栈

```bash
make deploy-ec2-down
```

如果要连 volume 一起删除，可在后续通过环境变量扩展控制。

## Bifrost Gateway

[deploy/docker-compose.yml](../deploy/docker-compose.yml) 保留了 Bifrost gateway 服务，但默认作为 **可选 profile** 关闭。

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

[deploy/docker-compose.yml](../deploy/docker-compose.yml) 中的 observability 服务默认是 **可选 profile**，而不是默认启动。

如果确实要启用，可以在运行前设置：

```bash
export DEPLOY_ENABLE_OBSERVABILITY=true
```

然后再执行 `make deploy-ec2-up`。

## 与本地 smoke 的边界

请保持以下职责分离：

- [deploy/docker-compose.yml](../deploy/docker-compose.yml) → **EC2 / 正式部署入口**
- [deploy/docker-compose.local-s3.yml](../deploy/docker-compose.local-s3.yml) → **本地生产形态演练，使用 MinIO 模拟 S3**
- [docker-compose.db.yml](../docker-compose.db.yml) → **本地 / CI smoke 和测试环境**

不要把两者重新揉成一套，否则会让部署面和测试面相互污染。

## 本地生产形态演练

如果 smoke 已经通过，想在上 EC2 前确认生产 compose、secret 注入、前端反代、worker、migration 和 S3 形态，可以运行本地演练栈：

```bash
make deploy-local-prod-secrets-prepare
make deploy-local-prod-check
make deploy-local-prod-up
make deploy-local-prod-wait
make deploy-local-prod-verify
```

这套命令会：

- 使用 `deploy/docker-compose.yml` 作为主体。
- 叠加 `deploy/docker-compose.local-s3.yml`，只额外加入 MinIO 模拟 S3。
- 使用 `secrets/local-prod`，不复用 `secrets/ec2` 的真实部署 secret。
- 默认把 frontend 暴露到 `http://localhost:8080`，避免占用本机 80 端口。
- 不启动 observability profile，也不拉入 `docker-compose.db.yml` 中的 Tempo / smoke-only 组件。

查看日志和停止：

```bash
make deploy-local-prod-logs
make deploy-local-prod-logs ARGS="api"
make deploy-local-prod-down
```

## 后续自动 CD 的接入方式

未来如果接 GitHub Actions / SSM，推荐复用现有手动入口，而不是重写一套部署逻辑。

理想做法是：

1. CI 负责 build / push images
2. SSM 或远程执行负责调用：
   - `make deploy-ec2-secrets-prepare`
   - `make deploy-ec2-check`
   - `make deploy-ec2-up`
   - `make deploy-ec2-wait`
   - `make deploy-ec2-verify`
3. 失败时通过 `make deploy-ec2-logs` 收集排障信息

也就是说：

> 自动 CD 应该只是“替你执行已经稳定的人工部署流程”，而不是重新发明第二套流程。
