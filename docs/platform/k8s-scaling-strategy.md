# Kubernetes 扩缩容策略

职责：解释 Dewflow Backend 为什么需要扩容、按什么信号扩容，以及如何限制扩容风险。
边界：本文描述 k8s 接入方案和容量策略，不替代真实生产压测结论；当前生产验收路径仍以 compose / EC2 为准。
副作用：无；实际参考清单位于 `deploy/k8s/`。

## 核心判断

Dewflow 的扩容对象分成两类：

| 对象 | 压力来源 | 当前指标 | 扩容组件 | 策略 |
| --- | --- | --- | --- | --- |
| API | 在线 HTTP 请求 | CPU / Memory | HPA | 1-5 副本 |
| Worker | 后台任务积压 | Redis list length | KEDA | 1-8 副本 |

API 和 Worker 的压力模型不同，所以不能只用一套指标。API 关注在线请求的响应余量，Worker 关注 TaskIQ 队列是否堆积。

## 为什么扩 API

API 负责登录、权限、知识库上传入口、聊天入口、任务状态查询和流式响应入口。它的压力通常来自在线请求并发增加。

当前使用 Kubernetes 原生资源指标：

- CPU 平均利用率达到 70% 时触发扩容。
- 内存平均利用率达到 75% 时触发扩容。
- 副本数限制在 1-5，避免无上限挤压数据库、Redis 或 LLM 下游。

这是一套基础但稳妥的策略，不依赖应用额外暴露指标。后续如果有真实流量，可以接入 Prometheus Adapter，把 API 扩容指标升级为 RPS、P95 延迟或 in-flight requests。

## 为什么扩 Worker

Worker 负责 LLM 非流式生成、知识库解析、chunking、embedding 和向量入库等后台任务。它的压力不一定体现在 API CPU 上，而是体现在 Redis 中等待消费的 TaskIQ 队列。

当前使用 KEDA Redis scaler：

- Redis db=1 是 TaskIQ 队列库。
- TaskIQ list 名称为 `taskiq`。
- 队列长度达到 10 左右时触发扩容。
- 每 15 秒检查一次队列长度。
- 队列下降后等待 120 秒再缩容。

这条链路更贴近异步任务系统的真实压力：

```text
任务进入 Redis -> 队列长度升高 -> KEDA 扩 Worker -> 消费能力提升 -> 队列下降 -> 保守缩容
```

## 阈值怎么估算

`listLength: 10` 是初始阈值，不是固定真理。它可以按任务吞吐估算：

```text
单个 Worker Pod 启动 2 个 taskiq worker
单任务平均耗时 30 秒
1 个 Pod 每分钟约处理 4 个任务
如果希望排队等待不超过 2 分钟
队列长度超过 8-10 时就应该开始扩容
```

后续可以根据真实任务耗时、LLM provider 限流和数据库写入能力调整该阈值。

## 风险控制

扩容不是越多越好。Worker 扩太快可能打满 LLM provider、embedding provider、Postgres 连接池或 Redis。

当前保护措施：

- API 设置 `maxReplicas: 5`。
- Worker 设置 `maxReplicaCount: 8`。
- API 和 Worker 都配置 CPU/内存 requests 与 limits。
- API readiness probe 检查数据库可用，避免不可用 Pod 接流量。
- Worker liveness probe 检查 TaskIQ 进程和 Redis broker 可用。
- 应用层保留 `LLM_MAX_CONCURRENCY` 和 `DB_MAX_CONCURRENCY` 并发限制。

生产化前需要通过压测校准副本上限、队列阈值和下游服务配额。

## 观测状态说明

### 当前状态

- 当前生产验收路径仍是 compose / EC2，不是 k8s。
- 当前 AWS 生产环境的监控以云端托管服务为准，不以 `deploy/monitoring/` 下的本地自托管配置为 source of truth。
- 当前这份文档中的 HPA / KEDA 方案，主要用于说明未来 k8s 接入时的扩缩容信号选择。

### 条件成立时可用

- 当后续真的启用 k8s 路径时，API 可以先用 Kubernetes 原生 CPU / Memory 指标扩容。
- 当 worker 继续使用 Redis TaskIQ 队列时，可用 KEDA Redis scaler 按队列积压扩容。
- 当需要 richer observability 时，应再决定是走 Prometheus Adapter、自托管指标链路，还是云端托管指标接入。

### 目标态

推荐演进顺序：

1. 当前阶段：HPA 使用 CPU/内存，KEDA 使用 Redis 队列长度。
2. 观测增强：在真正启用 k8s 路径后，再让 FastAPI `/metrics`、Prometheus 和 Worker / 业务指标接入同一套 observability contract。
3. API 指标升级：通过 Prometheus Adapter 使用 RPS、P95 延迟或 in-flight requests 扩容。
4. 生产保护：增加 PDB、NetworkPolicy、资源配额、告警规则和压测报告。
