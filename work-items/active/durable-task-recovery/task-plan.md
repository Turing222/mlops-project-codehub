# 工作项计划：持久任务恢复与 Redis 职责隔离

> 机读状态（`status`、`workstreams`、`current_checkpoint`、`next_choices`、
> `open_decisions`）只保存在 `manifest.yaml`，并以它为准。
> 本文件只记录稳定叙事：为什么做、范围是什么、取舍是什么。

## 目标

让已经被系统接受的 Chat generation 与 Knowledge ingestion 在 DB commit、Redis enqueue、Worker 启动/退出等故障边界后，都能在有上限的时间内恢复，或进入明确且可重试的失败终态。PostgreSQL 是业务事实源，Redis 只承担缓存或任务传输职责；目标是“至少一次执行 + 业务终态至多一次”，不是承诺外部服务 exactly-once。

本工作项落实[后端综合升级路线 T1-4](../../../docs/assessments/2026-07-17-backend-consolidated-upgrade-roadmap.md#54-t1-4--任务持久化恢复与-redis-职责隔离)，并复用 [T1-3 工作项](../chat-generation-consistency/task-plan.md)已经验证的 generation request、attempt、lease 与 terminal settlement 合同。

## 对话结论

- 单人推进时只保持一个主要实现链：先用失败测试固定边界，再依次完成 Chat、Knowledge、Redis，最后统一做故障注入；不同时维护多个 migration 或跨域半成品。
- T1-4 有三个独立验收 checkpoint：Chat recovery、Knowledge durable ingestion、Redis 职责隔离。任一 checkpoint 未验证，都不能把 T1-4 标为完成。
- 不抽象通用 workflow 基类。Chat 与 Knowledge 保留各自状态机，只统一稳定业务 ID、CAS claim、lease / due、恢复预算、结构化事件和 `AbstractTaskDispatcher` 边界。
- Chat 的 `attempt` 继续表示一次业务生成尝试；broker 派发次数必须单独计数，不能因为 Redis enqueue 重试而增加业务 attempt。
- Chat 的 `PREPARED` 与未被 Worker claim 的 `QUEUED` 可以由 reconciler CAS 接管并重新派发。每次派发都设置下一次 `recovery_due_at`，达到可配置预算后写入 `FAILED + retryable=true`。
- Chat Worker 必须实际续租 heartbeat。`RUNNING` lease 过期后先 fence 旧 lease，再进入明确的可重试失败；首期不自动重放可能已经调用过 LLM 的 attempt，用户只能通过 T1-3 的显式 retry 创建下一 attempt。
- 重复扫描、重复 broker 消息和晚到旧 Worker 都允许发生，但只有当前 attempt 与 lease token 能 claim 或提交终态。
- Knowledge 采用专用 `TaskOutbox`，因为当前 `TaskJob` 不具备 publish claim、lease、attempt、due 与唯一消息合同。`File + TaskJob + TaskOutbox` 必须在一个事务中提交。
- Knowledge relay 只保证 at-least-once dispatch；Worker 通过条件 claim 和稳定 job identity 消费。重复消息不得重复写 chunks、重复推进终态或重复结算。
- `redis-cache` 可继续使用 eviction policy；task broker / result backend 使用独立 `redis-taskiq`，配置 `noeviction`、AOF、持久卷和明确 result TTL。隔离不声称修复 `ListQueueBroker` 的破坏性 pop，可靠性仍由 DB durable state 与 reconciler 提供。
- T1-4 只输出 T1-5 所需事件与字段，不在此工作项配置 CloudWatch、SNS、值班流程或生产阈值。

## 恢复合同与故障矩阵

| 边界 | 持久事实 | T1-4 收敛行为 |
| --- | --- | --- |
| Chat DB 已提交，Web 在派发前退出 | `PREPARED` 且 `recovery_due_at` 到期 | reconciler CAS 转入可派发状态并安排同一业务 attempt。 |
| Chat 已标记 `QUEUED`，Redis enqueue 失败或 Redis 全量重启 | request、broker message identity 与 due 仍在 PostgreSQL | 有预算地重新派发；重复消息由 claim CAS 去重。 |
| Chat Worker 在生成中被终止 | `RUNNING`、lease 与最后 heartbeat 可审计 | lease 到期后 fence 旧 Worker并写入可重试失败，不盲目调用 LLM。 |
| Chat 旧 Worker 晚到 | attempt / lease 已失效 | terminal settlement CAS 拒绝写 message、Credits 与成功终态。 |
| Knowledge DB commit 前失败 | 整个 UoW 回滚 | 不产生孤立 File、TaskJob 或 outbox。 |
| Knowledge DB 已提交，relay / Redis 失败 | TaskOutbox 仍为待发布 | relay 有预算地重发并记录最近错误；达到上限后保持可告警、可人工重放状态。 |
| Knowledge 收到重复消息或 Worker 被重启 | TaskJob claim 状态与稳定 job identity 存在 | 仅一个 Worker 获得处理权，重复投递不产生第二份业务结果。 |
| Broker Redis 重启 | PostgreSQL durable state 保留，broker 使用 AOF 与 volume | 重启后由 relay / reconciler 补齐遗漏；所有非终态最终恢复或明确失败。 |

## Workstream 拆分理由

### WS1 — Freeze T1-4 recovery contracts and characterize the current crash windows

- Scope：固定上面的恢复语义，核对 Chat、Knowledge、Redis 的现有状态字段、事务边界、派发路径和 scheduler 落点。
- Reason：自动恢复会放大重复调用与重复结算风险，必须先区分“可以安全重派发”与“只能 fence 后显式 retry”。
- Expected effect：migration、repository、scheduler、Worker 和部署配置共享同一故障矩阵，不在实现中临时改变 attempt 含义。

### WS2 — Add failing boundary tests for Chat, Knowledge, and Redis recovery

- Scope：补 Chat PREPARED / QUEUED due、RUNNING lease expiry、重复 scan / delivery；Knowledge 原子创建、outbox relay / claim；Redis 重启后收敛的失败基线。
- Reason：这些测试既证明当前缺口，也定义后续三个 checkpoint 的停止线。
- Expected effect：生产代码切换前，每个确认的 crash window 都由可重复的 `current_*` 测试记录；默认套件保持绿色，后续实现逐项翻转预期。

### WS3 — Implement Chat CAS recovery and the generation-request reconciler

- Scope：增加派发预算字段与 CAS、实际 Worker heartbeat、周期 reconciler、过期状态 fencing、稳定恢复事件，并经 `AbstractTaskDispatcher` 派发。
- Reason：T1-3 已建立持久 request，但 Web 在 queue CAS 后派发失败仍会留下永久 `QUEUED`，长任务也没有续租。
- Expected effect：`PREPARED` / `QUEUED` 可有界恢复，`RUNNING` 终止可有界失败，重复处理不能越过 attempt / lease fence。

### WS4 — Implement Knowledge durable ingestion, outbox relay, and conditional claim

- Scope：新增 additive migration、`TaskOutbox` ORM / repository、单事务 upload UoW、relay、Worker 条件 claim、状态 reconciler 与幂等写入保护。
- Reason：当前 File、TaskJob 与 dispatch 分处不同提交边界，现有 recovery job 只能把 stale 状态标失败，无法补发已接受任务。
- Expected effect：DB commit 成功后任务可追踪并可补发，重复投递只产生一个 TaskJob 终态和一份 chunk 结果。

### WS5 — Isolate cache Redis from the persistent task broker and result backend

- Scope：拆分配置与 Compose 服务，保留缓存实例的 eviction 特性，为 broker / result 实例配置 `noeviction`、AOF、volume、healthcheck 与 result TTL；同步测试环境变量。
- Reason：当前单实例 `allkeys-lru` 会让缓存压力驱逐任务相关键，且无持久化卷，职责与故障域均未隔离。
- Expected effect：缓存淘汰不影响任务传输，任务 Redis 重启有明确持久化行为，同时应用仍通过现有 dispatcher 边界运行。

### WS6 — Validate restart, duplicate-delivery, and worker-termination convergence

- Scope：在可丢弃环境执行 DB commit / enqueue 边界、全量 Redis restart、重复 delivery、Worker SIGKILL、晚到 attempt 与恢复预算耗尽矩阵。
- Reason：unit test 不能证明真实进程、Redis 持久化和 scheduler 组合后的收敛行为。
- Expected effect：每个非终态在规定时间内恢复或明确失败，Chat 不重复 settlement，Knowledge 不重复写 chunks。

### WS7 — Record the T1-5 observability handoff and close T1-4

- Scope：固定 recovery 结构化事件、错误码、ID、attempt / dispatch count、lease、due、outbox 状态与手工 replay 入口，并更新路线图 / work item 证据。
- Reason：T1-5 需要直接消费稳定信号，不能靠日志文本猜测任务是否卡死。
- Expected effect：T1-4 可独立 validated，T1-5 获得可实施的指标与告警输入。

## WS2 失败基线证据

WS2 沿用 T1-3 的通过式 failure characterization：测试名以 `current_*` 标记尚未修复的合同，测试本身保持绿色，避免把预期失败长期留在默认 CI。对应实现落地时必须把原断言改成目标合同，不能直接删除测试。

| 基线 | 当前已确认行为 | 后续翻转点 |
| --- | --- | --- |
| Chat dispatch | request 已进入 `QUEUED` 后 broker enqueue 可失败，SSE 返回 `CHAT_DISPATCH_FAILED + retryable=false`。 | WS3 reconciler 有预算地补派发同一业务 attempt。 |
| Chat lease | Worker claim 时只设置一次 lease，完整生成过程中没有调用 heartbeat。 | WS3 增加实际续租与过期 fence。 |
| Chat scheduler | 必需 schedule 与 scheduler modules 中没有 generation recovery scanner。 | WS3 注册并校验 Chat reconciler schedule。 |
| Knowledge transaction | File 和 TaskJob 分属两个 UoW，二者提交后才调用 broker。 | WS4 改为 `File + TaskJob + TaskOutbox` 单事务。 |
| Knowledge duplicate delivery | `mark_processing` 不校验 expected status，可把 `COMPLETED` task 回退到 `PROCESSING`。 | WS4 使用条件 claim 并拒绝 terminal regression。 |
| Knowledge schema | `TaskJob` 没有 attempt / lease / due / publish 字段，metadata 中也没有 outbox table。 | WS4 additive migration 与 repository contract。 |
| Redis failure domain | Compose 只有一个 `allkeys-lru` Redis，无 AOF、无 volume；TaskIQ fallback 只换 DB。 | WS5 拆分 cache 与 task Redis 并增加持久化。 |

Focused baseline 共 40 个相关测试通过，其中 8 个为本工作项新增的 `current_*` 合同。

## WS3 实施入口

- 首期派发预算固定为最多 3 次（首次 dispatch 加两次 recovery dispatch），使用现有 `CHAT_GENERATION_QUEUE_RECOVERY_SECONDS=300` 作为固定 due 间隔；暂不引入指数 backoff。
- `attempt` 继续只表示业务生成 attempt。新增的 dispatch 计数只服务于 broker 补派发预算，不能触发新的 LLM 业务 attempt。
- 第一 checkpoint 只做 additive migration、ORM、repository due scan / CAS 与真实 PostgreSQL 合同测试，不接 scheduler，也不改变 Web / Worker 行为。
- 第二 checkpoint 接入 reconciler：`PREPARED` CAS queue，`QUEUED` 保持相同 attempt / broker message identity 有预算补派发；达到预算后进入 `FAILED + retryable=true`。
- 第三 checkpoint 增加 Worker heartbeat，并让过期 `RUNNING` 先失效旧 lease、再进入可显式 retry 的失败终态；不得自动重新调用 LLM。
- 最后注册 scheduler、翻转 WS2 的三个 Chat `current_*` 断言，并运行真实 PostgreSQL / Redis focused matrix。WS3 不修改 Knowledge outbox 或 Redis 拓扑。

## WS3 验证证据

2026-07-17 已完成 Chat recovery checkpoint：

- `chat_generation_requests.dispatch_attempts` 使用独立非负计数，现有已派发记录回填为 `1`；显式业务 retry 重置计数，首次 queue 与后续 broker 补派发分别递增，不改变业务 `attempt`。
- PostgreSQL 同时保存 versioned `dispatch_context`。Web 在提交 `PREPARED` 时已持久化 stream / nonstream 模式与 Worker payload，因此 DB commit 后、首次 queue 前退出仍可恢复；非流式补派发使用 fire-and-forget dispatcher，不在 recovery Worker 内等待另一个 Worker 的 result。
- repository 提供有界且确定排序的 due scan，并用 `status + attempt + task_id + lease_token + dispatch_attempts + recovery_due_at` 精确 CAS 保护补派发或预算耗尽失败。重复 scanner、晚到 delivery 与晚到 terminal write 均不能越过 fence。
- scheduler 每分钟触发 generation reconciler。到期 `PREPARED` 生成稳定 attempt fence 后派发；`QUEUED` 保持同一 `attempt`、`task_id`、`lease_token` 有预算补发；到期 `RUNNING` 只写 `FAILED + retryable=true`，不自动重放可能已调用 LLM 的 attempt。
- Worker claim 后通过独立 UoW 立即并周期续租；heartbeat 失败或旧 lease 晚到仍由 terminal settlement CAS 拒绝越权写 message 和 Credits。
- migration revision `8c1d7e4a9b20` 以 `5f4c2a9d8e71` 为父 revision；一次性 PostgreSQL 已验证空库 `upgrade head -> downgrade 5f4c2a9d8e71 -> upgrade head`。
- 真实 PostgreSQL / Redis 覆盖 PREPARED service 接管、QUEUED 单 scanner CAS、预算耗尽时 request/message 原子失败、RUNNING 过期 fence、稳定 TaskIQ wire identity，共 `11 passed`；完整 backend unit 为 `1011 passed / 9 skipped`，component 为 `42 passed`。
- Ruff、Alembic 单 head / orphan、config、import boundary、layer dependency、test marker 与类型检查均通过；类型检查仍只报告仓库既有的 16 个 diagnostics。`qa-no-while-true` 仍仅被既有 `scripts/qa/check_serena_mcp.py:52` 阻断。

该证据关闭 WS3 的 Chat recovery checkpoint，不代表 Knowledge ingestion 已持久化，也不代表 Redis broker 已完成隔离或重启演练；这些边界分别由 WS4、WS5、WS6 验收。

## WS4 验证证据

2026-07-17 已完成 Knowledge durable ingestion checkpoint：

- migration revision `2a7c9e4d1b63` 以 `8c1d7e4a9b20` 为父 revision；`TaskJob` 增加结构化 `knowledge_file_id / knowledge_base_id`、worker `attempt_count`、heartbeat 与 lease，`task_outbox` 固定 `(task_id, event_type)` 唯一业务事件、publish attempt / due / lease / error 与 `PENDING -> PUBLISHING -> PUBLISHED / DEAD` 状态。
- Web 上传只使用一个共享 UoW 提交 `File + TaskJob + TaskOutbox`，commit 后才做 best-effort 快速 publish。Redis 或快速 publish 失败不会把已接受文件写成伪失败；事务体内失败会补偿新对象，commit 回执不确定时保留对象以避免删除可能已经提交的业务数据。
- relay 每分钟通过 `FOR UPDATE SKIP LOCKED` 有界 claim，使用 outbox UUID 作为稳定 TaskIQ message identity；Redis 写入失败释放为下次 due，确认前退出由 publish lease 过期接管，预算耗尽进入可告警、可人工 replay 的 `DEAD`。
- Knowledge Worker 只允许 `PENDING -> PROCESSING` 条件 claim，claim 时递增业务 attempt 并写 lease；独立 heartbeat 与解析/索引事务内的 attempt 续租共同 fence 旧 Worker。完成、失败和 chunks cleanup 都不能越过当前 attempt，重复 broker 消息对 `PROCESSING / COMPLETED / FAILED / CANCELED` 直接 ack。
- 原来分别 bulk 标记 File/Task 失败的入口已移除。reconciler 按结构化 FK 逐对处理 `UPLOADED` 孤儿、`PENDING` 无 active outbox、`READY` 未完成 task、`FAILED` 未终结 task 与过期 `PROCESSING`；前三次 worker attempt 可重置并通过同一 outbox 重投，预算耗尽时 File/Task 同事务失败。
- 一次性 PostgreSQL 已验证空库 `upgrade head -> downgrade 8c1d7e4a9b20 -> upgrade head`；真实 PostgreSQL / Redis 覆盖 attempt fence、重复 claim、晚到 terminal、active-file 唯一约束、outbox 唯一事件、claim/publish 和稳定 wire identity，共 `4 passed`。完整 backend unit 为 `1024 passed / 9 skipped`，component 为 `42 passed`，TaskIQ focused 为 `2 passed`。
- Ruff、Alembic 单 head / orphan、config、import boundary、layer dependency、test marker 与类型检查均通过；类型检查仍只报告仓库既有的 16 个 diagnostics。`qa-no-while-true` 仍仅被既有 `scripts/qa/check_serena_mcp.py:52` 阻断。

该证据关闭 WS4 的 Knowledge durable ingestion checkpoint，不代表 cache Redis 与 task broker 已隔离，也不代表真实 restart / SIGKILL 故障矩阵已完成；这些边界分别由 WS5、WS6 验收。

## 暂缓 / 不纳入范围

- RabbitMQ、Redis Streams、Kafka、通用 DLQ、KEDA 或跨域通用 workflow / saga 框架。
- 外部 LLM、embedding 或 parser 的 exactly-once 保证；本项目只能 fence 自有业务写入。
- Chat 自动重放已经进入 `RUNNING` 的 attempt；首期选择明确失败与显式 retry，避免双重外部调用。
- T1-5 的实际监控平台、告警阈值、SNS 通知和完整 runbook 演练。
- T2-5 的 versioned SSE replay / `Last-Event-ID` 协议和产品级取消语义。

## Open Decisions 说明

当前没有需要用户阻塞确认的架构决策。派发预算的具体默认值与 backoff 将在 WS3 随 repository CAS 测试固定为可配置合同；它属于实现参数，不改变上述安全边界。
