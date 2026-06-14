# Local Worker Scaling Smoke Test

职责：用最小资源验证 KEDA 能根据 Redis 队列长度扩缩 `dewflow-worker`。
边界：这是 Worker-only 扩缩容链路演示，不部署 API，不运行完整业务任务；日常开发仍使用 `docker-compose.db.yml`。
副作用：会在本地 k8s 集群中创建 Redis、Worker Deployment 和 KEDA ScaledObject。

## 需要的本地组件

- Docker
- kind 或 minikube
- kubectl
- helm
- KEDA

如果只验证 Worker KEDA 扩容，不需要 metrics-server。metrics-server 只影响 API HPA 的 CPU/内存指标。

## 资源预算

本演示把 Worker 命令 patch 成 `sleep`，只验证扩缩容控制链路，避免本地机器跑完整 AI 任务。
因为不部署 API，任务不会通过 HTTP 入口投递；验证时需要手动向 Redis db=1 的 `taskiq` list 写入测试数据。

| 组件 | 副本 | 单副本上限 | 估算峰值 |
|---|---:|---:|---:|
| kind control-plane | 1 | - | 700Mi-1.5Gi |
| Redis | 1 | 256Mi | 50Mi-200Mi |
| Worker demo | 1-3 | 256Mi | 128Mi-768Mi |
| KEDA | 1-2 | 默认 | 100Mi-300Mi |

WSL 可用内存约 8G 时，这套演示通常比较稳。

## 验证步骤

安装 KEDA：

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda --namespace keda --create-namespace
```

构建并导入镜像：

```bash
docker build --target worker -t dewflow-backend:2.0.0-ai .
kind load docker-image dewflow-backend:2.0.0-ai
```

应用本地扩缩容演示：

```bash
cp deploy/k8s/local-scaling/secret.local.example.yaml /tmp/dewflow-secret.local.yaml
kubectl apply -k deploy/k8s/local-scaling
kubectl apply -f /tmp/dewflow-secret.local.yaml
kubectl -n dewflow wait --for=condition=available deploy/redis --timeout=120s
kubectl -n dewflow wait --for=condition=available deploy/dewflow-worker --timeout=120s
```

制造队列积压：

```bash
kubectl -n dewflow exec deploy/redis -- sh -c '
  for i in $(seq 1 12); do
    redis-cli -a "$REDIS_PASSWORD" -n 1 lpush taskiq "demo-$i" >/dev/null;
  done
'
```

这一步等价于模拟 TaskIQ 投递了 12 个等待任务。KEDA 会读取 Redis db=1 的 `taskiq` list 长度，并按 `listLength: 3` 把 Worker 扩到最多 3 个副本。

观察扩容：

```bash
kubectl -n dewflow get scaledobject
kubectl -n dewflow get hpa
kubectl -n dewflow get deploy dewflow-worker -w
```

清空队列，等待缩容：

```bash
kubectl -n dewflow exec deploy/redis -- \
  redis-cli -a "$REDIS_PASSWORD" -n 1 del taskiq
kubectl -n dewflow get deploy dewflow-worker -w
```

## 当前阈值

- Redis db：`1`
- Redis list：`taskiq`
- 扩容阈值：`listLength: 3`
- 最大副本：`3`
- 轮询间隔：`5s`
- 缩容冷却：`30s`

这个阈值只为本地演示降低了触发门槛；正式示例仍使用 `listLength: 10` 和更保守的缩容时间。
