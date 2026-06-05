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
- `SECRET_KEY`
- `GOOGLE_ALLOWED_REDIRECT_URIS`
- `POSTGRES_*`
- `REDIS_*`
- `S3_BUCKET`
- `LLM_PROVIDER` / `RAG_EMBED_PROVIDER`
- `DEPLOY_BASE_URL`
- `DEPLOY_PULL_IMAGES`

> 说明：如果在 EC2 本机执行验证，`DEPLOY_BASE_URL=http://localhost` 通常就够了；如果希望验证公网域名，也可以改成真实域名。
>
> `make deploy-ec2-*` 会自动把真实 deploy env 文件路径注入给 compose；只有在你把 deploy env 文件移到其他位置时，才需要通过 `DEPLOY_ENV_FILE=...` 覆盖默认路径。`DEPLOY_*` 控制项和镜像名可以用临时 shell 环境变量覆盖；应用运行时配置和 secrets 应写入真实 deploy env 文件。

## Makefile 入口

手动部署统一通过根目录 [Makefile](../Makefile) 暴露以下命令：

- `make deploy-ec2-check`
- `make deploy-ec2-up`
- `make deploy-ec2-wait`
- `make deploy-ec2-verify`
- `make deploy-ec2-logs`
- `make deploy-ec2-down`

这些命令底层调用：

- `scripts/deploy/ec2-check.sh`
- `scripts/deploy/ec2-up.sh`
- `scripts/deploy/ec2-wait.sh`
- `scripts/deploy/ec2-verify.sh`
- `scripts/deploy/ec2-logs.sh`
- `scripts/deploy/ec2-down.sh`

## 推荐部署顺序

### 1. 预检查

```bash
make deploy-ec2-check
```

这个步骤会检查：

- Docker / Compose 是否可用
- deploy env 文件是否存在
- 关键变量是否已填写
- compose 配置能否成功渲染

### 2. 启动 / 更新部署栈

```bash
make deploy-ec2-up
```

这个步骤会：

- 在 `DEPLOY_PULL_IMAGES=true` 时拉取镜像
- 启动核心服务
- 打印当前容器状态

### 3. 等待服务 ready

```bash
make deploy-ec2-wait
```

默认会检查：

- frontend health: `/healthz`
- API liveness: `/api/v1/health_check/live`
- API DB readiness: `/api/v1/health_check/db_ready`

### 4. 跑部署后 smoke 验证

```bash
make deploy-ec2-verify
```

这个步骤会复用现有 smoke 验证框架，但默认只跑更适合远端部署的子集：

- `tests/smoke/test_core_api_flow_smoke.py`
- `tests/smoke/test_chat_http_smoke.py`
- `tests/smoke/test_rag_http_smoke.py`

默认不把 knowledge smoke 作为第一轮 EC2 部署验证必跑项，因为它通常对 DB / storage 假设更深，适合后续逐步放开。

### 5. 查看日志

```bash
make deploy-ec2-logs
```

也可以指定服务名，例如：

```bash
make deploy-ec2-logs ARGS="api"
```

> 如果需要进一步增强，也可以后续把日志 target 改成更显式的服务参数形式。

### 6. 停止部署栈

```bash
make deploy-ec2-down
```

如果要连 volume 一起删除，可在后续通过环境变量扩展控制。

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
- [docker-compose.db.yml](../docker-compose.db.yml) → **本地 / CI smoke 和测试环境**

不要把两者重新揉成一套，否则会让部署面和测试面相互污染。

## 后续自动 CD 的接入方式

未来如果接 GitHub Actions / SSM，推荐复用现有手动入口，而不是重写一套部署逻辑。

理想做法是：

1. CI 负责 build / push images
2. SSM 或远程执行负责调用：
   - `make deploy-ec2-check`
   - `make deploy-ec2-up`
   - `make deploy-ec2-wait`
   - `make deploy-ec2-verify`
3. 失败时通过 `make deploy-ec2-logs` 收集排障信息

也就是说：

> 自动 CD 应该只是“替你执行已经稳定的人工部署流程”，而不是重新发明第二套流程。
