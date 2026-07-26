# 部署、韧性、可观测性与应用安全评估

> 日期：2026-07-17
> 范围：EC2 / Cloudflare Pages / Kubernetes 部署边界、Redis / TaskIQ、服务降级、日志与告警、CSP、secret 管理、数据与服务恢复能力
> 性质：基于当前仓库代码、部署清单和运维文档的时点评估；记录现状、风险、优先级与验收方向，不代表建议已经实施
> 证据基线：分支 `chore/deps-batch-patch`、提交 `af4f855`；同时参考当前 working tree 中两份 2026-07-15 计划文档
> 状态：冻结；未连接 AWS、Cloudflare、GitHub 或 Kubernetes 控制面，外部配置与运行状态必须另行实证

## 1. 结论速览

Dewflow 已具备一条可执行的单机生产路径：Cloudflare Pages 承载前端，Cloudflare Tunnel 把 API 流量送到单台 EC2，EC2 Compose 运行 API、Worker、Scheduler 和 Redis，生产数据落到外部 RDS 与 S3。镜像回退、数据库 migration gate、非 root 容器、file-backed secret、JSON 日志和基础 CloudWatch / SNS 接线已经形成可用基线。

当前仍不能把这套系统描述为高可用或可证明恢复的生产平台。最高风险不是 Kubernetes 清单不够完整，而是异步业务事实与 Redis / TaskIQ 生命周期没有闭环：Redis 无持久化且使用 `allkeys-lru`，TaskIQ list 消费缺少项目级确认、重试和 dead-letter 协议，Chat 与知识入库又没有完整的持久 job、outbox、lease 和 reconciler。Redis 重启、内存淘汰、Worker 在取任务后退出或 Web 等待超时，都可能造成任务丢失、重复执行或数据库状态长期悬挂。

| 领域 | 当前判断 | 风险级别 |
| --- | --- | --- |
| EC2 / Pages | 主路径清晰，具备手工发布和回退；单主机、单 Tunnel、单 Redis 仍是故障域 | 高 |
| Kubernetes | 仅为参考清单，不属于当前 production acceptance path | 不评级 |
| Redis / TaskIQ | 逻辑分 DB 但共享单进程；缺少 durable delivery 与恢复合同 | 严重 |
| 降级 | LLM、Planner、Rerank、外部检索已有局部 fallback；多数降级对调用方不可见 | 中高 |
| 可观测性 / 告警 | JSON 日志和 CloudWatch 脚本已存在；生产指标默认关闭，部分告警过滤器失效 | 高 |
| CSP / 应用安全 | 基础 header、限流和生产 guardrail 较好；CSP 不阻断且 JWT 存在 localStorage | 高 |
| Secret | 文件注入和启动校验较好；缺少托管生命周期、轮换审计和服务级最小权限 | 中高 |
| 恢复能力 | 镜像与 RDS runbook 较完整；任务、Redis、S3、EC2 与 Tunnel 恢复未闭环 | 严重 |

如果业务处于受控内测、低流量并接受人工恢复，当前路径可以继续使用；如果 Chat、RAG、知识入库和 Credits 已承载正式业务，则 durable task、告警闭环和恢复演练应作为上线阻断项。

## 2. 证据边界与当前拓扑

本报告使用三类证据：

1. **已确认实现**：当前代码、Compose、脚本或文档直接支持的事实。
2. **待外部实证**：仓库只描述要求，但是否在 AWS、Cloudflare、GitHub 或集群控制面启用无法从代码判断。
3. **计划能力**：assessment 或 work item 中提出但状态仍为 `planned` / `pending` 的目标，不计入当前能力。

本次没有读取 production secret，没有调用云控制面，也没有执行故障注入、恢复演练或真实公网 smoke。因此以下事项必须在线核验：

- RDS Multi-AZ、backup retention、PITR、snapshot 和 restore drill 记录；
- Cloudflare Pages production branch、环境变量、deployment history、Tunnel credential 与公网健康；
- GitHub branch protection、required checks 和 Security CI 实际门禁；
- CloudWatch log group retention / KMS、metric filter 计数、Alarm 状态和 SNS 收件人确认；
- S3 versioning、default encryption / KMS、lifecycle、跨区复制和对象恢复能力。

当前生产拓扑可概括为：

```text
Cloudflare Pages
       |
Cloudflare edge / Tunnel
       |
127.0.0.1:8081 -> api-nginx
       |
单台 EC2: API + TaskIQ Worker + Scheduler + Redis
       |
RDS PostgreSQL + S3 + 外部模型 / 检索服务
```

[deploy-ec2.md](../platform/deploy-ec2.md#L3) 明确把单台 EC2 + Docker Compose 定义为当前正式部署入口；[frontend-delivery-and-edge-responsibilities.md](../platform/frontend-delivery-and-edge-responsibilities.md#L1) 则把 Pages 和容器 fallback 的职责分开。这个边界合理，但也意味着 Pages、Tunnel、EC2 和云数据库分别有自己的控制面与恢复责任，不能只通过 Compose healthcheck 证明端到端可用。

## 3. 部署与发布能力

### 3.1 EC2 / Pages 主路径

当前主路径已有以下正向能力：

- API、Worker 和 migration 使用独立容器，`db_migrator` 成功后才启动 API / Worker。
- API edge 默认只绑定 `127.0.0.1:8081`，避免客户端绕过 Tunnel 伪造 `CF-Connecting-IP`。
- 后端容器使用非 root 用户，Compose 启用 `no-new-privileges` 并设置资源上限。
- 后端使用不可变 release tag；Pages 保留 deployment history，容器前端只承担 fallback。
- RDS 使用 `verify-full` 的生产默认值；S3 优先使用 EC2 instance profile。

这些能力主要记录在 [deploy-ec2.md](../platform/deploy-ec2.md#L17) 和 [docker-compose.yml](../../deploy/docker-compose.yml#L96)。

主要限制如下：

- 单台 EC2 同时承载 API、Worker、Scheduler、Redis 和 Tunnel 进程，主机、磁盘、网络或 AZ 故障会造成整栈中断。
- API 与 Worker 各只有一个容器；`restart: unless-stopped` 能处理部分进程故障，不能替代副本、故障域分散或容量接管。
- Pages 在 production branch push 后立即构建，与 GitHub CI 并行；真正的发布门依赖外部 branch protection，仓库中的 weekly guard 只能审计，不能替代控制面配置。
- `ec2-up.sh` 主要执行 pull / up / ps；发布失败没有自动回滚、蓝绿或 canary。
- 基础 wait 只覆盖 API liveness、DB readiness 和可选 frontend，不证明 Worker 能消费任务，也不证明 Redis、S3、Tunnel 或真实模型链路可用。
- 数据库 migration 若不向后兼容，镜像回退不能恢复 schema，仍依赖 snapshot、PITR 或 forward fix。

因此当前发布成熟度是“可重复的人工发布”，不是“自动判定、自动止损和自动恢复的持续交付”。

### 3.2 Kubernetes 现状

[deploy/k8s/README.md](../../deploy/k8s/README.md#L4) 明确声明 Kubernetes 目录只是参考清单，不属于当前 production acceptance path。该目录已有 API HPA、Worker KEDA、非 root 容器和 migration Job 示例，但仍存在生产阻断项：

- API、Worker 和 Scheduler 初始副本均为 1，HPA / KEDA 最小副本也是 1；
- knowledge storage 示例仍是 local + `ReadWriteOnce` PVC，与多副本不兼容；
- Redis、PostgreSQL、Ingress、TLS 和 Bifrost 都依赖外部补齐；
- 未形成 PDB、NetworkPolicy、topology spread、anti-affinity 和完整 container hardening 合同；
- Secret 通过普通 Kubernetes Secret + `envFrom` 注入，没有 External Secrets / Secrets Store CSI 等托管来源；
- migration Job 与 workload 一起 apply，缺少明确的 rollout 编排与失败回退合同。

Kubernetes 可以改善调度、自愈和扩缩容，但不会自动修复 TaskIQ 的任务确认、DB / Redis 一致性或恢复协议。推荐先稳定业务状态机和可观测性，再决定是否生产化 Kubernetes。

## 4. Redis / TaskIQ 与异步韧性

### 4.1 Redis 故障域

应用 Redis 默认使用 DB 0，TaskIQ 使用 DB 1；[settings.py](../../backend/config/settings.py#L147) 的确避免了 key 命名混杂，但两个 DB 仍共享同一个 Redis 进程、内存上限和重启事件。

生产 Compose 中 Redis 的关键配置是：

```text
maxmemory 384mb
maxmemory-policy allkeys-lru
requirepass ...
```

当前没有挂载 Redis 数据卷，也没有显式 AOF / RDB 配置，见 [docker-compose.yml](../../deploy/docker-compose.yml#L98)。因此：

- Redis 重启会丢失队列、任务结果、幂等 key、限流窗口和 Pub/Sub 状态；
- `allkeys-lru` 可以淘汰 TaskIQ queue、result 或业务锁，而不只淘汰可重建缓存；
- DB 0 / DB 1 无法提供容量隔离，result key 或缓存增长会共同挤压队列；
- 单 Redis 同时影响 API mutation、认证限流、Chat、知识入库和 Worker，故障半径过大。

这不是简单的“缓存丢失”。当前 Redis 还承担任务投递和短期业务协调，应该按业务数据面而不是纯缓存来设计持久性、淘汰策略和告警。

### 4.2 TaskIQ 投递与结果语义

[task_broker.py](../../backend/infra/task_broker.py#L13) 使用 `ListQueueBroker` 和 `RedisAsyncResultBackend`。结合当前安装版本的 broker 实现，list 消费会在执行前通过破坏性 pop 移除消息；Worker 取出消息后退出时，没有 visibility timeout 或 ack / nack 将任务恢复到待消费队列。

项目层还存在以下缺口：

- task decorator 未形成统一 retry、最大尝试次数、退避、dead-letter 和 poison message 策略；
- result backend 未配置过期时间，结果可能长期占据 Redis 内存；
- Web dispatcher 手工构造 TaskIQ 私有 wire format，并直接读取内部 pickle result，升级依赖时容易静默不兼容；
- Web 等待超时只停止等待，不会取消已开始的 Worker provider 调用；
- Chat 没有与知识入库等价的 stale recovery；知识 recovery 也只是标记失败，不会重投；
- Redis Pub/Sub 没有持久事件、sequence 和 replay，断连后不能从最后事件恢复。

[task_dispatcher.py](../../backend/infra/task_dispatcher.py#L38) 已在源码注释中承认 wire format 和 pickle 属于内部兼容面；[2026-07-15-chat-rag-worker-reliability-plan.md](2026-07-15-chat-rag-worker-reliability-plan.md#L198) 也把 durable task lifecycle、deadline、retry / dead-letter 和 chat recovery 列为待实施项。

### 4.3 健康检查与故障表现

API readiness 只探测 PostgreSQL，liveness 只证明 FastAPI 进程存活，见 [health_check.py](../../backend/api/v1/endpoint/health_check.py#L19)。Worker healthcheck 只统计 TaskIQ 进程并执行 Redis `PING`，不验证 DB、S3、模型 provider 或真实任务消费，见 [healthcheck.py](../../backend/worker/tasks/healthcheck.py#L42)。

| 故障 | 当前可见行为 | 业务风险 |
| --- | --- | --- |
| Redis 重启 | 容器可自动重启，API / Worker 随后重新连接 | 队列、结果、锁和 Pub/Sub 事实丢失 |
| Redis 内存淘汰 | 未必导致健康检查失败 | 任务或幂等状态被静默删除 |
| Worker 取任务后退出 | 进程 healthcheck 最终失败并重启 | 已 pop 的 in-flight 任务可能永久丢失 |
| Web 等待超时 | 请求返回失败或停止 SSE 等待 | Worker 可能继续调用模型并晚到写状态 |
| DB commit 后 enqueue 前退出 | DB 中已有业务记录，Redis 没有任务 | 状态永久停留在 `PENDING` / `THINKING` |
| 重复投递或旧 Worker 晚到 | 缺少统一 attempt / lease 条件提交 | 新状态可能被旧执行覆盖或重复结算 |

稳定目标应是：数据库保存 durable request / job，业务事务同时写 outbox；relay 至少一次投递；Worker 使用 attempt、lease 和条件状态更新保证幂等；超时任务由 reconciler 收敛；Redis queue 只承担可恢复的传输，不再是唯一业务事实。

## 5. 降级与外部依赖韧性

项目已经具备有价值的局部降级：

- `resilient` LLM route 可以在候选 provider 间 fallback；
- Planner 失败时回退默认 plan；
- Rerank 失败时保留原始候选排序；
- Tavily / 外部检索故障时降级为空结果；
- GrowthBook 故障时使用本地缓存或代码默认值；
- 多个外部调用已有 timeout 和进程内 circuit breaker。

这些设计能让主链路继续返回结果，但目前多数是静默降级。外部检索真实返回空与调用失败后返回空，对上层通常具有相同形态；用户、前端和 SLO 很难区分“没有证据”与“证据服务不可用”。这会把可用性问题转换成答案质量和可信度问题。

另外需要注意：

- circuit breaker 是进程内状态，多 Worker 时失败阈值按进程分散；
- streaming provider fallback 通常只能发生在首个 chunk 之前，已经输出后不能安全切换模型；
- 单 provider 配置没有真实替代路径；
- embedding / ingestion 的暂态失败缺少统一 retry 与 deadline；
- Redis 限流路径没有明确的故障策略，Redis 异常可能把受限接口变成 5xx，而 readiness 仍保持正常。

建议为降级建立统一信号，例如 `degraded_components`、`route_fallback`、`retrieval_status` 和稳定 `error_code`，至少进入结构化日志、指标和 audit；影响答案可信度时再向前端暴露用户可理解的降级状态。

## 6. 可观测性与告警

### 6.1 已有基础

当前基础设施并非完全没有观测：

- Compose 使用 `awslogs` driver，把 API、Worker、Redis、Nginx 等容器日志送入 CloudWatch；
- Python logger 输出 JSON，包含时间、level、logger、代码位置，并在可用时附带 trace / span；
- API Nginx access log 包含 request ID、状态码和请求耗时；
- FastAPI 可以通过 OpenTelemetry 输出 metrics / traces；
- 仓库提供 CloudWatch Logs metric filter、Alarm 和 SNS topic 的配置脚本；
- circuit breaker、rerank degradation 和 CSP violation 已有部分结构化 event。

这些能力为故障调查提供了日志基础，但尚未形成“核心 SLO -> 指标 -> 告警 -> 人员触达 -> runbook -> 恢复验证”的完整闭环。

### 6.2 生产指标和 trace 缺口

生产 Compose 默认 `ENABLE_OTEL_METRICS=false`、`ENABLE_OTEL_TRACES=false`，见 [docker-compose.yml](../../deploy/docker-compose.yml#L90)。FastAPI 的 `/metrics` endpoint 返回空字符串，只能作为 endpoint 存活占位，见 [main.py](../../backend/main.py#L101)。

API 启动会调用 `setup_telemetry(app)`，Worker startup 当前只调用 `setup_logging()` 并获取 lazy container，见 [task_broker.py](../../backend/infra/task_broker.py#L21)。因此仓库不能证明 Worker 已向同一后端导出 metrics / traces，也不能证明 Web dispatch 与 Worker execution 具有完整的跨进程 trace。

当前缺少的核心指标至少包括：

| 领域 | 最低信号 |
| --- | --- |
| API | request count、5xx rate、P50 / P95 / P99、并发和 timeout |
| TaskIQ | queue depth、oldest message age、enqueue / start / success / failure / retry、执行时长 |
| Worker / Scheduler | heartbeat、active tasks、stuck tasks、restart count、schedule lag |
| Redis | memory、evicted keys、rejected connections、latency、restart、persistence 状态 |
| RDS | connections、free storage、CPU、free memory、read / write latency、backup failure |
| 外部依赖 | provider route、错误率、首 token 延迟、总时长、circuit state、degradation count |
| 公网链路 | Pages、Tunnel、API、SSE 与关键业务 synthetic check |
| 数据一致性 | outbox backlog、oldest pending age、reconcile action、orphan object / record |

[alarms-cloudwatch.md](../../deploy/monitoring/alarms-cloudwatch.md#L57) 已把 API latency、5xx、Redis memory 和 RDS 指标列为 Phase 2，这些仍应视为未完成能力。

### 6.3 已确认的告警过滤缺陷

[cloudwatch-setup.sh](../../deploy/monitoring/cloudwatch-setup.sh#L82) 创建以下两个 JSON filter：

```text
{ $.error_code = "LLM_ROUTING_FAILED" }
{ $.error_code = "KNOWLEDGE_FILE_INGEST_FAILED" }
```

但 [exception_handlers.py](../../backend/core/exception_handlers.py#L48) 只把 `exc.code` 格式化进日志 `message`；`error_code` 只出现在 HTTP response body，没有通过 logger `extra` 写入 JSON 顶层。知识入库 Worker 的异常日志也没有形成同名顶层字段。因此这两个 filter 与当前日志合同不匹配，Alarm 很可能不会计数。

其他告警局限包括：

- 只有 5 个 log-based 信号，不能覆盖延迟、错误率、队列和资源饱和；
- `treat-missing-data=notBreaching` 会让日志投递中断时继续显示正常；
- setup 脚本没有为 log group 配置 retention 或 KMS；
- SNS topic 创建后仍需人工订阅并确认收件人；
- 没有 heartbeat / dead-man alarm 证明 Worker、Scheduler 和日志链路仍在工作；
- CSP report endpoint 明确只写日志，不落库、不直接告警。

最低修复应先统一结构化 logging contract，并在非生产环境触发每个稳定 `error_code` / `event`，验证“日志出现 -> metric 增长 -> Alarm -> SNS 邮件 -> OK 恢复”全链路。

## 7. 应用安全

### 7.1 已有安全基线

当前已经实现多项合理防线：

- production API docs 关闭，已知默认 JWT secret 和 production mock auth 会在启动时被拒绝；
- CORS、payload limit、认证入口 rate limit、SMS 猜码保护和可信代理 IP 解析已有实现；
- API edge 默认不直接暴露公网，容器以非 root 运行并启用 `no-new-privileges`；
- Pages / fallback 提供 `nosniff`、frame、referrer 和静态缓存 header；
- Python / frontend dependency audit、容器 Trivy 扫描、Dependabot 和 GitHub Action SHA pinning 已存在。

这些能力能阻止明显的错误配置和常见滥用，但不能替代浏览器 XSS 防护、token 隔离、secret 生命周期和数据最小化。

### 7.2 CSP 与浏览器 token

[generate-pages-headers.mjs](../../frontend/apps/admin/scripts/generate-pages-headers.mjs#L24) 生成的策略仍是 `Content-Security-Policy-Report-Only`，且包含：

```text
script-src 'self' 'unsafe-inline' 'unsafe-eval'
style-src 'self' 'unsafe-inline' ...
```

`object-src 'none'`、`base-uri 'self'` 和 `frame-ancestors 'self'` 是有效的收敛项，但 Report-Only 不会阻止攻击，`unsafe-inline` / `unsafe-eval` 又显著削弱脚本注入约束。构建和 Pages verify 只证明 header 存在、report URI 正确，没有证明策略已进入 enforcement 或危险 source 已移除。

前端 auth store 把 JWT 持久化到 localStorage，[auth-store.ts](../../frontend/apps/admin/src/stores/auth-store.ts#L31) 的源码注释也承认 XSS 可读取 token。注释把“no eval”列为当前缓解，但实际 CSP 仍允许 `unsafe-eval`，两处安全叙述不一致。

推荐 rollout：

1. 给 CSP report 做去敏、聚合和 dashboard，先识别真实 allowlist；
2. 优先移除 `unsafe-eval`，再用 nonce / hash 或代码调整收敛 inline script / style；
3. 在 preview / canary 启用 enforcement，观察阻断和核心流程；
4. 全量切换 `Content-Security-Policy`，Report-Only 仅保留下一版策略预演；
5. 把 bearer token 迁移到后端设置的 `HttpOnly + Secure + SameSite` cookie，并重新评估 CSRF。

### 7.3 Secret 生命周期与最小权限

[secret_env.py](../../backend/core/secret_env.py#L16) 只允许白名单中的 `FOO_FILE` 加载，部署脚本会创建受限目录并检查必需 secret、占位符和明文误配，这是比直接把 key 写入 `.env` 更好的基线。

当前剩余风险是：

- EC2 secret 仍是人工维护的主机文件，没有 Secrets Manager / SSM、KMS、版本、自动轮换和访问审计；
- API 与 Worker 都挂载完整 `x-app-secrets`，服务间没有按实际依赖拆分最小集合；
- 文件读取后写入进程环境，容器内进程被攻破时仍可读取；
- secret 文件为兼容非 root 容器使用 `0644`，安全性依赖外层目录持续保持 `0700`；
- 主机丢失后，secret 和 Tunnel credential 的恢复与轮换没有可验证 runbook；
- Kubernetes 示例使用普通 Secret + `envFrom`，没有托管 secret provider。

推荐按 API、Worker、Migrator、Bifrost 分拆身份和 secret 集合；AWS 路径优先使用 instance role 与 Secrets Manager / SSM，保留 file injection 作为运行时落点，而不是人工文件作为唯一事实源。

### 7.4 供应链与观测数据边界

[security-ci.yml](../../.github/workflows/security-ci.yml#L1) 已覆盖 dependency 和 image vulnerability scan，但还没有形成完整的软件供应链保证：

- Security CI 不在当前 required status checks 清单中，且部分 PR trigger 只关注依赖、镜像和 workflow 路径；
- 未发现仓库级 secret scanning、SAST、IaC policy scan、SBOM、镜像签名或 provenance 验证；
- Trivy 使用 `ignore-unfixed`，需要结合风险接受流程解释未修复项；
- runtime image 使用版本 tag 而不是 digest，发布侧没有签名验证证据。

应用观测还需要数据最小化复核。LLM / Langfuse 路径可能记录完整 generation payload 和输出，guardrail metadata 也可保存原始 unsafe output；CSP 和 frontend telemetry 会记录 URI、source file 或调用方 metadata。生产前应定义字段 allowlist、PII / credential redaction、采样、保留期和访问权限，避免为了可观测性复制完整会话、query secret 或不安全内容。

## 8. 恢复能力

### 8.1 发布与数据库恢复

后端不可变镜像 tag、Compose 手工回退和 Pages deployment history 提供了发布级恢复入口。其局限是：

- 没有自动 rollback、流量切换或 rollback health gate；
- migration 若包含不可逆 schema 变化，旧镜像可能无法读取新 schema；
- Pages、API 和 migration 分属不同发布面，回退顺序需要人工协调；
- fallback 前端只有显式 profile 启动，不是自动故障接管。

[rds-backup-and-restore.md](../platform/rds-backup-and-restore.md#L14) 要求 automated backup、PITR、发布前 snapshot 和 restore drill，并建议记录 RPO / RTO。这是正确的 runbook，但仓库不能证明 AWS 已启用这些设置，也没有演练产物证明能在目标时间内完成实例恢复、应用切换和回切。

### 8.2 任务与跨存储恢复

知识上传当前跨越对象存储、`knowledge_files`、`task_jobs` 和 Redis enqueue 多个提交边界。普通异常可以 best-effort 补偿，但进程在任意两个边界之间退出时，仍可能产生对象孤儿、`UPLOADED` 无任务、`PENDING` 无 Redis 消息或 Redis 已投递但 DB 未确认。

知识 recovery 每 15 分钟运行，见 [knowledge_tasks.py](../../backend/worker/tasks/knowledge_tasks.py#L70)，但 [knowledge_ingestion_recovery_service.py](../../backend/services/knowledge_ingestion_recovery_service.py#L1) 明确只把长期中间态标记为失败，不重投、不删除对象，也不修复索引。当前还没有：

- transactional outbox 与 relay；
- durable inbox / consume dedup；
- attempt、lease、heartbeat 和 compare-and-set 状态更新；
- dead-letter queue 与人工 replay；
- `UPLOADED` / `PENDING` 联合对账；
- DB 对象记录与 S3 object 的双向 reconciler；
- Chat generation 和 Credits 的等价 recovery。

[2026-07-15-knowledge-ingestion-data-consistency-plan.md](2026-07-15-knowledge-ingestion-data-consistency-plan.md#L11) 已给出 outbox、条件状态流转、联合对账和 storage lifecycle 的实施路线，但其性质仍是计划，不能计入当前恢复能力。

### 8.3 基础设施与数据介质恢复

| 对象 | 当前恢复入口 | 未证明能力 |
| --- | --- | --- |
| 后端镜像 | 不可变 tag 手工回退 | 自动回退、canary、schema 兼容 gate |
| Pages | Cloudflare deployment history | 自动接管、Dashboard 配置 IaC、恢复演练 |
| RDS | backup / PITR / snapshot runbook | 实际 retention、Multi-AZ、restore drill、RPO / RTO |
| S3 | 依赖 AWS bucket 控制面 | versioning、KMS、lifecycle、误删恢复、对象对账 |
| Redis | 容器重启 | 队列 / result 持久化、HA、PITR 或可证明重建 |
| TaskIQ job | 少量 stale marker | retry、DLQ、replay、outbox、幂等消费 |
| EC2 | Compose 和部署文档 | AMI / IaC 重建、跨 AZ 接管、secret / Tunnel 恢复 |
| Bifrost | 本地 named volume | volume backup、恢复和多副本一致性 |
| CloudWatch / SNS | setup 脚本 | retention、KMS、订阅确认、灾备与配置漂移检测 |

恢复成熟度可分成四层：

1. **进程恢复：部分具备。** Compose restart 和 healthcheck 可以重启部分进程。
2. **发布恢复：基本具备。** 镜像和 Pages 可以人工回退，但 migration 需要额外治理。
3. **业务状态恢复：不足。** Task、Chat、Credits、知识文件与 Redis 没有统一可重放事实。
4. **主机 / AZ / 数据灾难恢复：未证明。** 缺少演练记录、自动化重建和确定 RPO / RTO。

在定义恢复目标时，应按用户可感知业务而不是单个组件制定。例如：

| 业务能力 | 建议先确认的恢复目标 |
| --- | --- |
| 登录与基础读取 | Redis 故障时哪些接口继续可用，恢复后限流状态如何处理 |
| Chat generation | 已接受请求不静默丢失；恢复后能查询最终状态或明确失败 |
| 知识入库 | 对象、文件、job、chunk 和索引最终收敛，可安全重投 |
| Credits | 同一逻辑请求最多结算一次，失败与退款有持久审计 |
| 发布 | 新版本失败后可在目标时间内回退，schema 仍兼容 |
| RDS 灾难 | 明确允许的数据回退窗口和恢复到新实例的切换时间 |

## 9. 推荐优先级与验收

### 9.1 P0 — 先保证业务事实不静默丢失

#### P0.1 Durable task 与状态一致性

推荐先复用两份 2026-07-15 计划中的共同 primitive：

- DB durable request / job 作为状态事实源；
- 业务事务内写 transactional outbox；
- bounded relay 执行至少一次投递并记录 attempt；
- Worker 使用 lease、heartbeat 和条件更新；
- consumer 对稳定业务 ID 幂等；
- reconciler 处理 stale、未投递、重复和晚到执行；
- 超过最大尝试次数进入 dead-letter 并支持受控 replay；
- Chat、Credits、知识入库和对象删除共享终态语义。

最低验收：

1. 在 DB commit 前后、Redis enqueue 前后和 Worker start / finish 各注入一次进程退出，状态都能自动收敛。
2. 同一消息重复投递不会重复生成最终消息、chunk、索引或 Credits 结算。
3. Worker 取任务后被 `SIGKILL`，任务会重试或进入可告警、可 replay 的 dead-letter。
4. Redis 全量重启后，DB 中所有非终态 job 都能被重建或明确标记失败，不永久悬挂。

#### P0.2 Redis 职责与持久性

至少把可淘汰缓存与 durable broker / result 隔离。目标方案可在以下路径中选择，但必须先写明交付语义：

- 使用具备 ack / visibility / retry 的 TaskIQ broker；
- 采用 Redis Streams、RabbitMQ 或其他 durable broker；
- 若阶段性继续使用 Redis，至少使用托管 HA、持久化、`noeviction`、独立实例 / 集群和明确 result TTL。

不能只给当前 Redis 增加 AOF 就宣称问题解决：AOF 可以减少重启丢失，但无法恢复已经被破坏性 pop 的 in-flight 消息，也无法替代业务 outbox 和幂等状态机。

#### P0.3 告警闭环

优先统一 `error_code`、`event`、`task_name`、`job_id`、`attempt` 和 `duration_ms` 的结构化字段，再修复 CloudWatch filters。首批必须告警：

- API 5xx 与高延迟；
- queue depth / oldest age；
- Worker / Scheduler heartbeat；
- task failure / retry / dead-letter；
- Redis memory / eviction / restart；
- EC2 status、磁盘、内存；
- RDS connections、storage、latency 和 backup failure；
- Tunnel / API / Pages 公网 synthetic failure；
- 日志链路 dead-man signal。

最低验收不是脚本执行成功，而是一次受控故障确实触发 SNS，并由值班人按 runbook 完成确认和恢复。

#### P0.4 恢复目标与演练

为 Chat、知识入库、Credits、RDS 和发布分别定义 RPO / RTO。至少完成：

- RDS snapshot / PITR 恢复到新实例并切换应用；
- Redis 重启和 Worker 中断后的 job reconciliation；
- 单台 EC2 丢失后的新主机部署、secret / Tunnel 恢复；
- S3 对象误删或版本恢复；
- migration 后应用回退和 forward-fix 演练。

每次演练保留时间、数据损失、人工步骤、权限、失败点和改进行动，而不是只记录“备份已开启”。

### 9.2 P1 — 收敛安全与可观测性

1. CSP 收集真实报告，移除 `unsafe-eval` / `unsafe-inline`，通过 preview / canary 切换 enforcement。
2. JWT 迁移到 HttpOnly cookie，并补 CSRF、登出、轮换和会话失效设计。
3. Secret 接入 Secrets Manager / SSM / KMS，按服务身份拆分权限并演练轮换。
4. API 与 Worker 统一 OTel，建立跨进程 trace、业务指标和 dashboard。
5. 对 Langfuse、CSP、frontend telemetry、日志和 guardrail metadata 实施 redaction 与 retention。
6. S3 启用并实证 versioning、default encryption / KMS、lifecycle 和对象 reconciler。
7. 把 Security CI 纳入合适的 required gate，并逐步补 secret / SAST / IaC / SBOM / signature 能力。

### 9.3 P2 — 再生产化 Kubernetes

只有在 P0 的业务交付与恢复合同稳定后，再推进：

- 托管 RDS、Redis / broker、S3 和外部 secret provider；
- API / Worker 多副本、PDB、topology spread、anti-affinity；
- NetworkPolicy、专用 ServiceAccount、最小 RBAC 和完整 container security context；
- migration 与 rollout 顺序、失败回退和 backward-compatible schema；
- HPA / KEDA 使用经过验证的业务指标，避免只按 CPU 或瞬时 queue length；
- 集群、节点、Ingress、证书、应用和任务的统一观测与故障演练。

推荐依赖顺序：

```text
Durable job / outbox / idempotency
                |
Redis / broker isolation + retry / DLQ
                |
Metrics / alerts + restore drills
                |
CSP / secret / privacy hardening
                |
Kubernetes productionization
```

## 10. 文档与治理状态

当前两份相邻计划准确覆盖了业务一致性问题：

- [2026-07-15-chat-rag-worker-reliability-plan.md](2026-07-15-chat-rag-worker-reliability-plan.md)：Chat / RAG / Worker 状态、恢复、流式协议、安全与质量；
- [2026-07-15-knowledge-ingestion-data-consistency-plan.md](2026-07-15-knowledge-ingestion-data-consistency-plan.md)：知识入库 outbox、状态流转、存储、索引血缘和迁移。

两份文档都明确标记为计划，后续实施应通过 work item 或 PR 更新现行规范，不能直接修改冻结 assessment 来宣称完成。

另一个治理风险是 [security-operability-baseline/manifest.yaml](../../work-items/active/security-operability-baseline/manifest.yaml#L32) 仍把 CSP / CloudWatch 的 WS4 标为 `pending`，但仓库已经存在 CSP endpoint、Pages header generator 和 CloudWatch setup 脚本。这说明机读 checkpoint 与代码状态发生漂移。应先复核 WS4 的实际交付和线上验证，再决定标记完成、拆出缺陷修复，或创建后续 workstream。

建议将本报告的 P0 结论沉淀为独立 durable work item；长期部署与恢复合同分别回写 `docs/platform/`，实现过程与 checkpoint 放入 `work-items/`，本 assessment 保持冻结作为 2026-07-17 的证据快照。

## 11. 最终结论

Dewflow 当前的强项是部署边界逐渐清晰，基础安全 guardrail 和人工运维入口已经存在；弱项是异步系统的可靠交付、跨存储一致性、可证明告警和可演练恢复。单纯增加更多容器、迁移 Kubernetes 或继续扩展 fallback，都不会替代 durable business state。

近期最有价值的主线是：

1. 先用 DB job / request、outbox、lease、幂等消费和 reconciler 消除静默丢任务；
2. 再隔离 Redis / broker 职责，补 retry、dead-letter、deadline 和 replay；
3. 同时修复结构化日志与告警，定义并演练 RPO / RTO；
4. 随后收敛 CSP、浏览器 token、secret 生命周期和观测数据隐私；
5. 最后把已验证的运行合同迁移到多副本 Kubernetes。

达到上述 P0 前，当前系统可以被描述为“具备单机生产部署基线”，不宜描述为“高可用、任务不丢、可自动恢复的生产平台”。
