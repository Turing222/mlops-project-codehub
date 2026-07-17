# Dewflow Kubernetes 接入示例

职责：沉淀 Dewflow Backend 迁移到 Kubernetes 的最小部署入口。
边界：当前生产验收路径仍以 [deploy/docker-compose.yml](../docker-compose.yml) + [docs/platform/deploy-ec2.md](../../docs/platform/deploy-ec2.md) 为准；本目录保留 Kubernetes 参考清单、扩缩容设计和后续接入草案，不改变 compose 运行方式。
副作用：应用这些清单会在目标集群创建 namespace、ConfigMap、knowledge PVC、`db-migrator` Job，以及 API / Worker / Frontend 对应的 Deployment、Service、HPA 和 KEDA 扩缩容对象。

## 状态说明

- **当前主路径**：单台 EC2 + Docker Compose；本目录不是当前 production acceptance path。
- **当前用途**：Kubernetes 参考清单、扩缩容讨论和本地/预演环境验证。
- **使用方式**：需要继续推进 k8s 时，再按实际集群、域名、TLS 和监控方案细化；不要把这里的示例直接当成当前正式部署合同。
- **外部依赖前置**：主 overlay 不创建 PostgreSQL / Redis；应用前必须先提供可解析的 `postgres`、`redis-cache` 与 `redis-taskiq` Service，或把 `configmap.yaml` 中的对应 host 改成实际 RDS / ElastiCache endpoint。缓存与 TaskIQ broker/result 必须是不同 Redis 实例。
- **镜像占位**：清单中的 `dewflow-backend:2.0.0-*` 和 `dewflow-frontend:2.0.0` 只是示例 tag；实际部署前必须替换为 `make release-image-env` 和前端发布流程产出的不可变镜像 tag。

## 已知实验缺口

- 主 overlay 当前仍使用 `STORAGE_BACKEND=local` + RWO `knowledge-files-pvc.yaml` 示例,与 API HPA / Worker KEDA 多副本扩缩容不构成生产合同。
- `configmap.yaml` 中的 `RAG_RERANK_PROVIDER=bifrost` 是占位配置,本目录没有提供 Bifrost Deployment;正式推进 k8s 前需要改为空值、接外部网关,或补齐 Bifrost 清单。

## 设计目标

- API 和 Worker 分开部署，匹配现有 `Dockerfile` 的 `web` / `worker` 镜像目标。
- API 作为在线 HTTP 服务，通过 HPA 按 CPU/内存扩缩容。
- Worker 作为异步任务消费者，通过 KEDA 按 Redis TaskIQ 队列积压扩缩容。
- Postgres、Redis、MinIO/S3 作为外部依赖接入；本地验证继续参考 `docker-compose.db.yml`。

## 扩缩容策略

详细设计见 `../../docs/platform/k8s-scaling-strategy.md`。

API 压力来自在线请求，示例策略为：

- `minReplicas: 1`
- `maxReplicas: 5`
- CPU 平均利用率 70%
- 内存平均利用率 75%

Worker 压力来自后台任务积压，示例策略为：

- `minReplicaCount: 1`
- `maxReplicaCount: 8`
- 独立 TaskIQ Redis db=0
- TaskIQ list 名称：`taskiq`
- 队列长度达到 10 时触发扩容

## 前端部署

前端作为独立的单页应用 (SPA) 通过 Nginx 提供服务：
- **资源利用**: 镜像中移除了所有源码和 node_modules，仅保留构建产物和 nginx 配置，内存和 CPU 开销较低。
- **安全加固**: Nginx 默认监听 `8080` 端口，Deployment 强制启用 `runAsNonRoot: true`，以非 root 用户 UID `101` (nginx) 运行。
- **网络暴露**: Frontend 服务通过 `Service` 暴露在集群内部 (ClusterIP)，并通过外部 `Ingress` 与后端 API 统一暴露；Ingress 会将外部 `/api/v1/...` 重写为后端 `/v1/...`。
- **镜像前置条件**: 部署前需要先构建并推送 `dewflow-frontend:2.0.0` 到集群可拉取的镜像仓库，或替换 `frontend-deployment.yaml` 中的镜像名。

## 使用方式

本地只验证 Worker 会根据 Redis 队列扩缩容时，优先看 `./local-scaling/README.md`。

1. 先复制并替换 Secret 示例，不要把真实密钥提交到仓库：
   ```bash
   cp deploy/k8s/secret.example.yaml /tmp/dewflow-secret.yaml
   ```

2. 构建并推送镜像，或将清单中的镜像名替换为已发布镜像：
   ```bash
   make image-build-release
   make frontend-image-build-release
   make release-image-env IMAGE_TAG="$(git describe --tags --always --abbrev=12)"
   # docker push <registry>/dewflow-backend:<tag>-web
   # docker push <registry>/dewflow-backend:<tag>-ai
   # docker push <registry>/dewflow-frontend:<tag>
   ```

3. 提供外部 PostgreSQL / Redis 连接入口。主 overlay 默认解析 `postgres.dewflow.svc.cluster.local`、`redis-cache.dewflow.svc.cluster.local` 和 `redis-taskiq.dewflow.svc.cluster.local`；可以手工创建 Service / ExternalName，也可以直接把 `configmap.yaml` 改为实际托管服务 endpoint。TaskIQ 实例需使用 `noeviction`、AOF 与持久卷。

4. 复制并根据实际域名配置 Ingress 示例（不包含在 Kustomize 资源内，需手动维护）：
   ```bash
   cp deploy/k8s/frontend-ingress.example.yaml /tmp/dewflow-ingress.yaml
   # 修改 /tmp/dewflow-ingress.yaml 中的 host 等配置
   ```

   > Ingress 示例表达的是**替代拓扑**，不是同一套规则的可叠加片段：
   > - `frontend-ingress.example.yaml`：单 host + `/api` 路径转发的统一入口方案。
   > - `api-ingress.example.yaml`：前后端分 host 的拆分入口方案。
   > 选择一种后再继续细化，不要直接混搭 path rewrite 和独立 host 规则。

5. 集群部署（标准部署入口使用 Kustomize 编排，`kubectl apply -k deploy/k8s` 会一并创建 `namespace.yaml`、`configmap.yaml`、`knowledge-files-pvc.yaml`、`db-migrator-job.yaml`，以及 API / Worker / Frontend 对应的 Deployment、Service、HPA 和 KEDA 资源）：
   ```bash
   kubectl delete job db-migrator -n dewflow --ignore-not-found
   kubectl apply -k deploy/k8s
   kubectl apply -f /tmp/dewflow-secret.yaml
   kubectl apply -f /tmp/dewflow-ingress.yaml
   ```

   > 注意：`db-migrator-job.yaml` 属于这次 Kustomize apply 的一部分；重复 apply 前需要先删除旧 Job，否则不可变字段会阻止重跑迁移。

如果集群没有安装 KEDA，需要临时跳过 `worker-keda-scaledobject.yaml`，Worker 仍可按 `worker-deployment.yaml` 的固定副本运行。
