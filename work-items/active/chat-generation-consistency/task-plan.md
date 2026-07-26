# 工作项计划：Chat generation 一致性与显式重试

> 机读状态（`status`、`workstreams`、`current_checkpoint`、`next_choices`、
> `open_decisions`）只保存在 `manifest.yaml`，并以它为准。
> 本文件只记录稳定叙事：为什么做、范围是什么、取舍是什么。
> 不要在这里复制状态字段。

## 目标

把 Chat 请求、消息、Credits settlement 和失败重试收敛到同一个 PostgreSQL 持久状态机。目标不是让外部 LLM exactly-once，而是允许任务至少一次执行，同时只允许当前 attempt 提交一次业务终态；Redis 只做锁、通知和缓存，前端不再依赖本地缓存猜测服务端事实。

本工作项落实 [后端综合升级路线 T1-3](../../../docs/assessments/2026-07-17-backend-consolidated-upgrade-roadmap.md#53-t1-3--chat-终态与-credits-一致性)，不吸收 T1-4、T1-5 或 Worker 大规模重构。

## 对话结论

- 项目由单人推进，默认只保持一个主要实现 workstream；小型只读核验可以穿插，但 migration、Web / Worker 切换和前端切换严格串行。
- 在第一档 validated 前，交付阶段按受控内测描述；不宣称任务不丢、自动恢复或高可用。
- 当前 generation request owner 使用 `user_id`，为未来 Workspace / tenant 预留 nullable 归属字段，不在本工作项做 Workspace 历史迁移。
- User Credits 是当前唯一生效账本；HTTP / SSE 断连默认不取消 Worker，结果继续持久化并从 DB 恢复。
- `generation_request_id` 表示跨 attempt 的业务身份；`client_request_id` 表示 `(user_id, client_request_id)` 幂等身份；`http_request_id` 只表示单次 HTTP 链路追踪。
- 首期使用服务端生成的 `generation_request_id`，并提供按当前 actor 与 `client_request_id` 解析持久 request 的协议。身份未知时先解析，不能生成新 ID 盲目重发。
- 最小状态流为 `PREPARED -> QUEUED -> RUNNING -> SUCCEEDED | FAILED`；只有 `FAILED + retryable=true` 可以通过 `expected_attempt` CAS 进入下一 attempt。
- 首期在 generation request 上保存 current attempt、lease、heartbeat 和最近 terminal 信息；不预建通用 attempt 历史表，除非回归测试证明单行模型无法满足审计或 CAS 不变量。
- 同一 generation request 最多产生一个最终 assistant message 和一次 Credits settlement；Redis 写失败不得逆转已提交的 PostgreSQL 终态。
- 旧前端兼容路径必须 fail-closed；新前端通过后端下发的 `chat-explicit-retry` flag 灰度，缺失 flag 默认 `false`。
- 在 Chat PR1 创建 Alembic revision 前，必须先完成或明确暂停现有 `storage-column-types` migration，避免单人并行维护两个未合并 migration。

## Workstream 拆分理由

### WS1 — Align the solo execution baseline and freeze T1-3 contracts

- Scope：固定 owner、Credits、断连、身份命名、状态流、retry CAS、迁移顺序和完成门槛；记录当前质量基线。
- Reason：这些合同会同时决定 migration、repository、Worker payload、API schema 和前端行为，必须先冻结。
- Expected effect：后续实现不再临时改变 request 身份或终态定义，已有失败与新回归可以明确区分。

### WS2 — Characterize current retry and settlement failures with regression coverage

- Scope：在现有测试落点补充 Worker 失败后同 ID 冲突、锁残留、历史重试新 ID、settlement 后 marker 逆转、meta 前断流和跨用户访问等失败基线。
- Reason：先证明当前行为，避免 migration 和工作流切换掩盖原始缺陷，也为三个 PR 提供稳定故障矩阵。
- Expected effect：每个已确认缺陷都有可重复测试，运行时条件性结论不会再被写成所有请求都会发生的事实。

### WS3 — PR 1 add the durable generation request schema and repository CAS contracts

- Scope：additive migration、ORM、repository、真实 PostgreSQL 唯一性 / CAS / 授权合同测试；不切换现有请求路径。
- Reason：先建立 DB 事实源，才能安全迁移 Web、Worker、Credits 和 retry 行为。
- Expected effect：`(user_id, client_request_id)` 只产生一个持久 request，旧 attempt 和越权 actor 都无法修改当前状态。

### WS4 — PR 2 switch web and worker paths to atomic terminal settlement

- Scope：Web 提交 `PREPARED` 后再 dispatch，Worker 使用 attempt / lease claim；消息、Credits 和 request terminal 在同一 UoW 中提交，Redis 失败只记录观测信号。
- Reason：这是消除静默扣费失败、终态回退和晚到 Worker 覆盖的核心切换点。
- Expected effect：DB commit、enqueue、Worker start / finish 和 Redis 故障边界都有单一、可解释结果。

### WS5 — PR 3 add authorized retry APIs and frontend integration behind a backend flag

- Scope：状态解析、显式 retry API、SSE / session detail additive 字段、稳定错误码、actor / tenant / session 授权，以及 `schemas -> api -> streams -> useChatStream` 前端切换。
- Reason：后端状态机只有被前端安全消费，T1-3 的失败重试验收才真正闭环。
- Expected effect：live、刷新后、RUNNING、不可重试和身份未知请求都由服务端状态驱动，前端不再通过 Map 复用或新 ID 回退重发。

### WS6 — Validate rollout behavior and hand off T1-4 recovery dependencies

- Scope：运行 flag-on / flag-off 故障矩阵、真实 PostgreSQL / Redis 集成验证和 monorepo 质量门；记录 `PREPARED` reconciler、lease 过期恢复及告警所需字段。
- Reason：T1-3 只证明终态和显式 retry，自动恢复与真实告警仍分别属于 T1-4 和 T1-5。
- Expected effect：T1-3 可以独立标记 validated，同时没有把恢复、告警或基础设施升级伪装成本工作项已完成能力。

## 暂缓 / 不纳入范围

- T1-4 的 Chat reconciler、Knowledge outbox / relay、Redis 实例隔离和自动 replay。
- T1-5 的 CloudWatch / SNS 告警交付与完整恢复演练。
- 完整 versioned SSE terminal 协议、`Last-Event-ID` replay 和用户取消协议；这些归 T2-5。
- 外部 LLM exactly-once、TaskIQ 盲目自动 retry、Redis Streams、Broker 替换和 Kubernetes。
- Workspace 全量迁移、Credits 主体迁移、通用 workflow / attempt 框架和 `worker_generation_workflow.py` 大规模重构。

## Open Decisions 说明

- `storage-migration-order`：当前已有 `storage-column-types` work item 准备新增 Alembic revision。推荐单人先完成该 migration，或明确将其设为 deferred；在此之前可以完成失败基线测试，但不创建 Chat migration。
- `quality-baseline-disposition`：当前 `flow-fast` 仍受 7 个既有 Ruff format 差异和 `scripts/qa/check_serena_mcp.py` 裸循环阻断。它们不属于 T1-3 行为修复，推荐作为独立 T1-1 小型清理处理；本工作项的 focused tests 已通过，但提交合并前仍应恢复完整绿色基线。

## WS6 验证结论

2026-07-17 的 rollout 与故障矩阵已验证以下边界：

| 场景 | 验证证据 | 结论 |
| --- | --- | --- |
| flag 缺失或关闭 | FeatureFlag 默认值、API component、Playwright 历史会话 | 默认 `false`；前端不暴露重试入口，后端返回 `CHAT_EXPLICIT_RETRY_DISABLED` 且不改变 request 状态。 |
| flag 开启且刷新后重试 | `chat-retry-flow.spec.ts`、`use-chat-stream.test.tsx`、stream workflow unit | 使用服务端 `generation_request_id` 与 `expected_attempt` 调用 retry endpoint；不回退到普通 `query_stream`，完成后仍只有一个 assistant message。 |
| RUNNING、已成功、不可重试、stale attempt | session orchestrator 参数化回归 | 分别返回稳定冲突码，不触发 retry CAS 或重复 dispatch。 |
| meta 前断流与身份未知 | `use-chat-stream.test.tsx` | 先按 client request identity 解析；解析失败时 fail-closed，不生成新 ID 盲重发。 |
| actor / Workspace / session 边界 | Chat API component 与真实 PostgreSQL repository tests | 跨 actor 隐藏为 404；只有仍有效的 Workspace membership 和 session 可读取或推进 request。 |
| 重复 settlement、晚到 Worker、Credits / DB 失败 | Worker persistence 与真实 PostgreSQL tests | message、Credits settlement 和 request terminal 由同一事务与 attempt / lease fence 保护；失败不会伪装为成功。 |
| Redis 清理或发布边界 | Redis failure unit 与真实 Redis pub/sub integration | Redis 清理失败不逆转 PostgreSQL 终态；结构化 `error_code` / `retryable` 经过真实 pub/sub 保持不变。 |

本矩阵证明的是 T1-3 的持久终态、授权查询和显式重试闭环，不等于自动恢复、任务不丢或高可用。

验证运行结果：后端 unit `985 passed / 9 skipped`、component `42 passed`、retry focused matrix `56 passed`；一次性 PostgreSQL `5 passed`、一次性 Redis `1 passed`；前端 Vitest `316 passed`、mock Playwright `13 passed`，production build 与 `461.9 KiB / 504.0 KiB` bundle gate 通过。Ruff lint、import boundary、test marker、Alembic、config、docs、skill 和 changed-scope format checks 通过；仓库级 format check 与 bare-loop gate 仍只被上文记录的既有 T1-1 债阻断，`ty` 以 16 个既有 warning、0 error 退出成功。

## T1-4 / T1-5 交接合同

T1-4 可直接复用 generation request 上的 `status`、`attempt`、`task_id`、`lease_token`、`heartbeat_at`、`lease_expires_at` 和 `recovery_due_at`，但后续实现仍必须单独证明：

- `PREPARED + recovery_due_at <= now` 由 reconciler 通过 CAS 接管，重复扫描不会重复 dispatch。
- `QUEUED` / `RUNNING` 的 lease 过期恢复会先 fence 旧 attempt，再执行有上限的恢复；不能启用 TaskIQ 盲目自动 retry。
- 达到恢复上限后写入明确 terminal failure，不让请求永久停留在 active 状态。

T1-5 的日志与告警至少关联 `event`、`error_code`、`http_request_id`、`generation_request_id`、`client_request_id`、`attempt`、`status`、`task_id`、`recovery_due_at` 和 `lease_expires_at`。最低告警场景为 PREPARED 超时、lease 过期、terminal settlement 失败、stale attempt / retry conflict 异常增长及 Redis publish 失败。实际告警规则、阈值、CloudWatch / SNS 交付和恢复演练均未在 T1-3 实现。
