# Chat / RAG / Worker 主链路治理实施计划

> 日期：2026-07-15
> 范围：Chat HTTP 入口、Web workflow、TaskIQ dispatcher、Worker generation、RAG、流式协议、消息持久化、Credits、安全观测与评测
> 性质：基于当前代码的实施路线图；记录现状、证据、推荐修改、依赖与验收，不代表修改已经完成
> 证据基线：分支 `chore/deps-batch-patch`、提交 `099ec68`
> 状态：planned；当前仅完成只读静态分析，尚未实施代码、迁移或测试改动

## 1. 结论与稳定目标

当前主链路的 Web / Worker 边界、RAG 模块分层和依赖生命周期总体合理，但存在一个比文件体积更优先的问题：Redis 幂等状态、TaskIQ 任务状态、数据库消息状态、Credits 结算和 SSE 传输终态没有统一协议。

本计划的稳定目标是：

1. 同一个逻辑请求只有一个可解释的持久终态，重复投递或旧 Worker 晚到不能改变它。
2. 数据库是 generation request 与消息终态的事实源；Redis 只承担锁、通知、事件或短期缓存职责。
3. LLM 调用允许 at-least-once，但最终状态只能提交一次，Credits 最多结算一次。
4. Web 断连、Worker 崩溃、Redis 故障和超时后，状态能够自动收敛，不永久停留在 `THINKING` 或 `RUNNING`。
5. `off`、`kb_only`、`web_only`、`auto` 的 RAG 行为对用户、前端和观测系统具有一致含义。
6. 安全拦截不会把 provider reasoning、原始敏感输出或完整会话默认扩散到非必要存储和观测系统。
7. 只有在行为契约和回归基线稳定后，才重构 Worker 编排结构。

本计划不包含 Agent 脚手架治理，也不把模型效果调优、UI 视觉调整或通用基础设施改造无边界地并入主链路工作。

## 2. 当前链路与证据边界

当前调用链为：

```text
HTTP
  -> Chat Web Workflow
      -> Redis idempotency lock
      -> DB user message + assistant THINKING
      -> feature flags / history snapshot
  -> TaskDispatcher -> TaskIQ Redis
  -> Worker
      -> input guardrail
      -> Planner -> KB/Web retrieval -> rerank -> evidence policy
      -> prompt assembly -> model routing -> LLM
      -> stream: Redis Pub/Sub -> Web SSE -> frontend
      -> non-stream: TaskIQ result backend -> Web
  -> Credits settlement + DB final message
  -> Redis completed marker
```

本报告中的“已确认”表示当前代码直接支持该结论；“建议”表示待实施的目标设计；“验证”表示后续工作必须补齐或执行的证据，不表示本轮已经运行。

已有基础包括：

- Web 通过 [`AbstractTaskDispatcher`](../../backend/contracts/interfaces.py#L221) 调用 Worker，没有直接 import `backend.worker`。
- Worker 依赖由 [`WorkerContainer`](../../backend/worker/dependencies.py#L37) 按进程缓存并在 shutdown 释放。
- RAG 已拆出 Planner、检索、Rerank、Evidence Policy、Context Builder 和 Citation Validator。
- 流式路径先订阅 Redis channel 再投递任务，降低首包丢失概率（[`web_stream_workflow.py`](../../backend/application/chat/web_stream_workflow.py#L152)）。
- Credits 服务已有基于 `chat_message_id` 的消费幂等记录，但 generation 终态与 Redis 仍未形成统一提交协议。

## 3. 必须先确认的不变量

| 不变量 | 推荐定义 |
| --- | --- |
| 请求身份 | `(user_id, client_request_id)` 唯一标识一个逻辑 generation request |
| 请求尝试 | 每次执行拥有独立 `attempt` 与 `lease_token`，只有当前 attempt 可以提交终态 |
| 持久事实源 | DB generation request 是业务状态事实源，`ChatMessage` 是展示内容，Redis 不是终态事实源 |
| 成功定义 | Credits 已确认或已按政策豁免、消息已提交、request 已转为 `SUCCEEDED` |
| 失败定义 | request 与 message 已转为一致的失败状态，并保留稳定 `error_code` |
| 流结束 | SSE `[DONE]` 只表示传输结束；业务成功由 terminal event 与 DB 状态决定 |
| 重试语义 | 同一个逻辑 request 可产生新 attempt，但不得产生第二次最终扣费或被旧 attempt 覆盖 |
| Redis 故障 | Redis 写入失败不得逆转已经提交的 DB / Credits 结果 |
| 断连语义 | 默认不因 HTTP 断连取消 Worker；结果继续持久化，客户端通过 DB 状态恢复 |

这些不变量是 WS1 的设计门；没有确认前，不应先做大规模 Worker 文件拆分。

## 4. 工作流与依赖关系

| ID | 工作流 | 类型 | 依赖 | 当前判断 |
| --- | --- | --- | --- | --- |
| WS1 | Generation request、幂等、消息与 Credits 一致性 | blocking | 无 | 最高风险，必须先完成 |
| WS2 | TaskIQ 生命周期、超时与故障恢复 | serial | WS1 | 当前缺少 durable task lifecycle 与 chat recovery |
| WS3 | 流式协议、断连与前端终态 | serial | WS1、WS2 | 当前可用但不可重放，终态语义分散 |
| WS4 | Guardrail、隐私与观测数据治理 | serial | WS1、WS3 | 数据盘点可提前，流式安全依赖 WS3 |
| WS5 | RAG 模式、历史、引用与评测 | parallel | WS1 | 数据集可提前准备，行为修改应服从 WS1 契约 |
| WS6 | Worker generation 结构重构 | serial | WS1–WS5 | 最后进行，只做已验证行为的结构收敛 |

推荐主路径：

```text
WS1 -> WS2 -> WS3 -> WS4 ----\
  \                              -> WS6
   +-----------> WS5 ----------/
```

为减少同一批核心文件上的冲突，实际交付仍建议按 `WS1 -> WS2 -> WS3 -> WS4 -> WS5 -> WS6` 推进；仅 WS5 的数据集整理和离线基线可以在 WS2、WS3 期间并行。

## 5. WS1 — Generation request、幂等、消息与 Credits 一致性

### 5.1 当前情况与依据

已确认问题如下：

- Redis key 使用 `user_id + client_request_id`，TTL 固定 300 秒（[`session_orchestrator.py`](../../backend/application/chat/session_orchestrator.py#L83)）；数据库却对 `client_request_id` 建立全局唯一索引（[`chat.py`](../../backend/models/orm/chat.py#L100)、[原迁移](../../alembic/versions/2026_02_28_2312-2207686616a6_add_token.py#L25)）。两个用户使用相同 ID 时，Redis 不冲突，DB 会冲突。
- Credits 预检明确传入空历史（[`session_orchestrator.py`](../../backend/application/chat/session_orchestrator.py#L143)），没有覆盖真实长上下文和最终模型路由成本。
- [`WorkerPersistenceHandler.persist_success()`](../../backend/application/chat/worker_persistence_handler.py#L50) 在 Credits 异常时把消息标为 `FAILED` 后直接返回；调用方仍继续写 Redis completed marker（[`worker_generation_workflow.py`](../../backend/application/chat/worker_generation_workflow.py#L351)）并返回 generation success。
- DB 消息与 Credits 提交后，如果 Redis marker 写入失败，异常会进入统一 failure handler，后者可以把已成功、已扣费的消息再次更新为 `FAILED`。
- Worker 只收到 `idempotency_lock_key`，没有 lock token 或 attempt version；成功时无条件 `SET`，失败时无条件 `DELETE`（[`worker_persistence_handler.py`](../../backend/application/chat/worker_persistence_handler.py#L37)）。
- Worker 失败会释放 Redis key，但失败消息仍保留原 `client_request_id`；前端重试复用相同 ID（[`use-chat-controller.ts`](../../frontend/apps/admin/src/features/chat/use-chat-controller.ts#L570)），下一次创建助手占位消息会撞唯一约束。

### 5.2 推荐修改

推荐新增持久化 `chat_generation_requests`，不继续让 Redis lock 和 `ChatMessage` 共同承担隐式状态机。建议最小字段如下：

```text
id
user_id
client_request_id
session_id
user_message_id
assistant_message_id
task_id
status
attempt
lease_token
reserved_credits
error_code
started_at
heartbeat_at
finished_at
created_at
updated_at
```

推荐状态机：

```text
PREPARED -> DISPATCHED -> RUNNING -> SUCCEEDED
                                \-> FAILED
                                \-> CANCELLED
                                \-> EXPIRED
```

实施步骤：

1. 在迁移前只读审计现有 `client_request_id` 重复、空 `user_id`、`THINKING`/`FAILED` 残留和 usage record 关联情况。
2. 新增 generation request ORM、repository、service/transition helper 和迁移；唯一约束使用 `(user_id, client_request_id)`。
3. 在同一 Web UoW 中创建 request、user message 和 assistant placeholder；Redis 只作为快速并发抑制，Redis miss 必须回查 DB。
4. Task payload 改传 `request_id + attempt + lease_token`；Worker 所有状态更新使用带当前 attempt/version 的条件更新。
5. `persist_success()` 返回明确 outcome，不再用 `None` 同时表示“成功”和“扣费失败”。消息、Credits settlement 与 request `SUCCEEDED` 在同一 UoW 提交。
6. Redis completed marker 改为提交后的 best-effort cache；写失败只记录稳定错误事件并等待修复/过期，不调用 `persist_failure()` 逆转 DB。
7. Credits 在 LLM 首次输出前进行 reservation：根据已组装 Prompt、实际选择模型和允许的最大输出预留；结束后按实际用量 settle 并释放差额。
8. 同一个逻辑 request 的失败重试创建新 attempt，并复用逻辑 request 与最终 assistant message；历史 attempt 保留在 request metadata 或独立 attempt 记录中。
9. 迁移稳定后再决定是否保留 `ChatMessage.client_request_id` 作为兼容字段，避免同一阶段同时删除旧索引和切换所有读取路径。

优先涉及的代码区域：

- `backend/models/orm/`、`backend/repositories/`、`backend/services/unit_of_work.py`
- `backend/application/chat/session_orchestrator.py`
- `backend/application/chat/worker_persistence_handler.py`
- `backend/application/chat/worker_generation_workflow.py`
- `backend/models/schemas/chat/payloads.py`
- `frontend/apps/admin/src/features/chat/use-chat-controller.ts`

### 5.3 验证

必须新增或扩展以下用例：

| 场景 | 预期 |
| --- | --- |
| 同一用户并发提交同一 ID | 只创建一个逻辑 request、调用一次 LLM、结算一次 Credits |
| 两个用户使用同一 ID | 两个请求均成功且互不读取对方结果 |
| FAILED 后复用同一 ID | 生成新 attempt，可完成且不触发唯一约束错误 |
| Redis `SET` / `DELETE` 失败 | DB 终态不被逆转，request 可由 DB 查询恢复 |
| Credits reservation 失败 | 首个业务 chunk 前失败，不产生 usage settlement |
| Credits settlement 重复执行 | 只存在一条最终 usage / spend 记录 |
| 旧 Worker 晚到 | CAS 失败，不能修改新 attempt 或最终消息 |
| request 创建事务失败 | request、user message、assistant message 一起回滚 |

Focused 验证建议：

```bash
uv run pytest \
  tests/unit/workflows/test_chat_nonstream_workflow_idempotency.py \
  tests/unit/workflows/test_worker_persistence_handler.py \
  tests/unit/workflows/test_worker_idempotency_and_error.py -q
make qa-alembic-check
make qa-boundaries
make qa-layer-deps
```

### 5.4 完成标准与依赖

WS1 无前置实现依赖，是 WS2、WS3 和 WS6 的 blocking dependency。只有以下条件全部满足才算完成：

- DB generation request 成为明确事实源。
- 并发、重试、跨用户、Redis 故障和旧 Worker 晚到用例通过。
- 扣费失败不会返回 success，Redis 故障不会把已扣费 success 改成 failure。
- migration upgrade/downgrade 与旧数据审计路径明确。

## 6. WS2 — TaskIQ 生命周期、超时与故障恢复

### 6.1 当前情况与依据

- [`TaskDispatcher`](../../backend/infra/task_dispatcher.py#L32)手工构造 TaskIQ Redis wire message；非流式结果通过 `pickle.loads` 读取 TaskIQ 内部 result shape（`:71-88`），升级兼容面依赖内部格式。
- `enqueue_nonstream()` 同时执行投递和最长约 330 秒的结果等待（`:109-129`）。Web 无法判断异常发生在投递前还是投递后，却在两种异常中都释放幂等锁（[`web_nonstream_workflow.py`](../../backend/application/chat/web_nonstream_workflow.py#L162)）。
- 非流式投递/等待异常路径没有像流式路径一样把已创建的 assistant placeholder 更新为 `FAILED`，可能遗留 `THINKING`。
- Chat task decorator 未配置项目级 retry、dead-letter 或 recovery；仓库已有知识入库 stale recovery（[`knowledge_tasks.py`](../../backend/worker/tasks/knowledge_tasks.py#L71)），没有等价 chat recovery。
- outbound wire 已有 broker formatter 单元契约测试（[`test_task_dispatcher.py`](../../tests/unit/infra/test_task_dispatcher.py#L203)）；现有 TaskIQ integration 只通过普通 `.kiq()` 发送 echo task（[`test_taskiq_integration.py`](../../tests/integration/test_taskiq_integration.py#L126)），没有覆盖真实 Chat dispatcher、Worker、DB 与 Redis 终态。
- Planner、Rerank 和外部搜索有显式 timeout；当前模型构造层未见项目级完整 generation deadline。Web SSE timeout 只停止等待，不等于取消 Worker provider call。

### 6.2 推荐修改

将 dispatcher API 拆为两个阶段：

```text
dispatch(request_id, attempt, lease_token) -> task_id
observe(request_id) -> durable terminal state
```

实施步骤：

1. Web 事务先提交 `PREPARED` request；投递成功后记录 `task_id` 并使用 CAS 转为 `DISPATCHED`。
2. Worker 领取任务后使用 `request_id + attempt + lease_token` 转为 `RUNNING`，记录 `started_at`，长任务更新 `heartbeat_at`。
3. 非流式 Web 不再依赖 TaskIQ 私有 pickle result 作为业务事实；等待 DB terminal state，Redis notification 只用于降低轮询延迟。
4. 增加 bounded chat reconciler，扫描超过阈值的 `PREPARED`、`DISPATCHED`、`RUNNING`：
   - `PREPARED` 未投递：允许重新 dispatch；
   - `DISPATCHED` 长时间未启动：使旧 attempt 失效后重新 dispatch 或标记失败；
   - `RUNNING` heartbeat 过期：先 revoke lease，再由产品策略决定自动重试或等待用户重试；
   - terminal state：永不重新 dispatch。
5. 在 WS1 fencing 完成前，不启用盲目 TaskIQ retry；否则旧执行与新执行可能并发生成并竞争终态。
6. 增加完整 Worker generation deadline，并为 planner、retrieval、rerank、model call 分配子预算；timeout 映射稳定 `error_code`。
7. 如果要求严格消除“DB commit 后、Redis enqueue 前崩溃”的窗口，再引入 transactional outbox；第一阶段可先用 `PREPARED + reconciler` 达到最终恢复。
8. TaskIQ wire format 继续保留 versioned shared payload schema；删除旧 positional compatibility 前，先确认没有旧 Web 实例或排队任务仍在使用。

推荐的交付语义不是 external LLM exactly-once，而是：

```text
Task 可以 at-least-once
当前 lease 才能提交终态
Message 只产生一个最终版本
Credits 最多结算一次
```

### 6.3 验证

需要新增真实跨边界 integration，并进行故障注入：

| 故障点 | 预期 |
| --- | --- |
| DB 创建 request 后、dispatch 前 Web 崩溃 | reconciler 发现 `PREPARED` 并恢复投递 |
| dispatch 后、Worker 领取前 Web 崩溃 | Worker 仍可完成，客户端从 DB 查询终态 |
| Worker 在 LLM 前、中、后被终止 | request 最终转为可重试 failure/expired，不永久 RUNNING |
| DB 提交后 result notification 失败 | DB success 保持，Web 可重新查询 |
| 旧 Task 在新 attempt 后恢复 | lease 校验失败，不写消息、不结算 Credits |
| provider 永久无响应 | Worker deadline 生效并进入稳定 timeout 状态 |
| reconciler 重复运行 | 不重复投递 terminal request，不重复扣费 |

Focused 验证建议：

```bash
uv run pytest tests/unit/infra/test_task_dispatcher.py -q
uv run pytest tests/integration/test_taskiq_integration.py -q
make qa-test-component
make qa-test-integration
```

应扩展 `tests/integration/test_taskiq_integration.py` 或新增 chat 专用 integration，使用 Web dispatcher 的真实 wire message启动真实 Worker，并验证 request、message、usage 和 terminal notification。

### 6.4 完成标准与依赖

WS2 依赖 WS1 的 request identity、attempt 和 lease。完成标准：

- dispatch 与 observe 职责分离。
- Chat 不再依赖 TaskIQ 私有 result pickle 作为业务终态。
- 所有非终态都有 bounded timeout 和恢复路径。
- Web/Worker 崩溃矩阵通过，无永久 `THINKING`/`RUNNING`，无重复 Credits。

## 7. WS3 — 流式协议、断连与前端终态

### 7.1 当前情况与依据

- 当前使用临时 Redis Pub/Sub channel；Web 在 dispatch 前订阅，但事件本身没有持久化、sequence 或 replay（[`web_stream_workflow.py`](../../backend/application/chat/web_stream_workflow.py#L152)）。
- 首消息 timeout 为 30 秒、消息间 timeout 为 10 秒（[`ai_settings.py`](../../backend/config/ai_settings.py#L110)）。timeout 结束 Web 等待，Worker 可能继续运行。
- 客户端断连后 endpoint 直接 `return`（[`chat_api.py`](../../backend/api/v1/endpoint/chat_api.py#L163)）；audit context 因无异常正常退出，当前会记录 success。
- Worker publisher 只有 `started`、`step`、`chunk`、`error`、`done`（[`worker_stream_publisher.py`](../../backend/application/chat/worker_stream_publisher.py#L22)），`done` 不携带 durable request 终态。
- Web 消费 Worker `started` 但不转发给前端；前端以 `[DONE]` 调用 `onDone`，收到 `error` 则提前返回（[`chat-stream.ts`](../../frontend/apps/admin/src/streams/chat-stream.ts#L98)）。
- 前端 `onDone` 会把剩余非 terminal trace steps 全部标为 `done`（[`use-chat-controller.ts`](../../frontend/apps/admin/src/features/chat/use-chat-controller.ts#L458)），无法区分未执行、跳过与降级。
- Pub/Sub、SSE、DB message、Redis completed marker 各自表达结束，缺少一个 versioned terminal contract。

### 7.2 推荐修改

第一阶段采用明确的非取消语义：HTTP/SSE 断连不自动取消 Worker；Worker 继续结算并持久化，客户端重新进入会话后读取 DB request/message 终态。理由是网络断连不等同于用户撤销，LLM 调用通常已经产生费用。

定义 versioned stream event contract：

```text
started(request_id, attempt, sequence)
step(request_id, sequence, step, status, metrics)
chunk(request_id, sequence, content)
terminal(request_id, sequence, message_id, status, error_code)
```

实施步骤：

1. 所有事件携带 `schema_version`、`request_id`、`attempt` 和单调递增 `sequence`。
2. `terminal` 只能在 WS1 的 DB/credits terminal commit 后发布；`[DONE]` 只在 `terminal` 后表示 SSE 传输完成。
3. Web timeout 或断连后不改 Worker 终态，记录 `client_disconnected` / `stream_observer_timeout`，并向前端提供 request status 查询入口。
4. 前端错误恢复以 request status/session detail 为准；不能仅凭本地累计 chunk 构造永久 success message。
5. Worker 必须为每个已计划 step 发布 `done`、`skipped`、`degraded` 或 `error`；前端停止把所有 idle step 自动改为 done。
6. 第一阶段保留 Pub/Sub，但明确 `non_resumable`，断连后通过 DB 获取最终完整内容。
7. 只有产品确认需要断点续传后，第二阶段才迁移到带 TTL 的 Redis Streams，并通过 `Last-Event-ID` / sequence 补发事件。
8. 显式用户取消作为后续独立能力：写入 durable cancel request，由 Worker 在安全检查点确认；不要把 TCP disconnect 当作 cancel。

### 7.3 验证

| 场景 | 预期 |
| --- | --- |
| 首包前断连 | Worker 按策略继续，request 可从 DB 查询 |
| 已输出部分 chunk 后断连 | 不重复生成，刷新后内容与 DB 终态一致 |
| Web 进程重启 | Worker 不受影响；旧 Pub/Sub 丢失被 DB status 恢复兜底 |
| error 后收到 `[DONE]` | 前端保持 failure，不转为 success |
| DB commit 前发布 terminal | 测试必须失败，禁止该顺序 |
| step 未执行或降级 | 前端显示 `skipped/degraded`，不能显示 done |
| 重复/乱序事件 | sequence 去重或拒绝，终态只处理一次 |
| 客户端正常完成 | terminal、`[DONE]`、DB message 三者一致 |

Focused 验证建议：

```bash
uv run pytest \
  tests/unit/workflows/test_chat_stream_workflow.py \
  tests/component/api/test_chat_api.py -q
make frontend-test
make frontend-e2e-mock
```

### 7.4 完成标准与依赖

WS3 依赖 WS1 的 durable request 和 WS2 的 task lifecycle。完成标准：

- `[DONE]` 不再承担业务 success 含义。
- disconnect、timeout、error、terminal 和 DB 状态的关系有统一协议。
- 前端能够在临时流丢失后恢复最终结果。
- stream 与 non-stream 使用同一 terminal state 和 error code。

## 8. WS4 — Guardrail、隐私与观测数据治理

### 8.1 当前情况与依据

- [`chat_safety_metadata.py`](../../backend/services/chat_safety_metadata.py#L1)与 [`safety_scanner.py`](../../backend/services/safety_scanner.py#L1)明确声明当前规则型 filter 可被同义改写和字符替换绕过，只适合作为早期数据收集能力。
- 流式路径对累计内容调用 output guardrail，但此前已经发布的 chunk 无法撤回（[`worker_generation_workflow.py`](../../backend/application/chat/worker_generation_workflow.py#L589)）。
- `<think>...</think>` 只参与 timing 判断，chunk 仍进入 publisher 和最终持久化；前端没有对应剥离逻辑。
- Guardrail 触发后，完整原始输出写入 `message_metadata.guardrail.output.original_unsafe_output`（[`chat_safety_metadata.py`](../../backend/services/chat_safety_metadata.py#L74)）。
- Langfuse generation 接收完整 `generation_payload` 和完整输出（[`llm_tasks.py`](../../backend/worker/tasks/llm_tasks.py#L120)、[`langfuse_utils.py`](../../backend/observability/langfuse_utils.py#L58)）；仓库代码层未见 payload 级 sanitizer。
- 用户输入在 Worker input guardrail 前已经创建为 DB user message，Langfuse generation 也在 workflow guardrail 外层创建。
- KB ingestion 使用 `SafetyScanner` 标记 `injection_risk`（[`ingestion_workflow.py`](../../backend/application/knowledge/ingestion_workflow.py#L222)），Context Builder 会对该 chunk 加提示；外部 Web chunk 当前没有同级扫描标记。

### 8.2 推荐修改

先建立内容数据流清单，对以下每一层记录 owner、原文需求、retention、访问权限、删除方式和是否外发：

```text
HTTP input
chat_messages
chat_generation_requests
TaskIQ Redis
stream transport
LLM provider
Langfuse
application logs
badcase / evaluation storage
```

实施步骤：

1. 增加统一 `TelemetryPayloadSanitizer` 或等价边界服务；默认 `capture_content=false`，仅记录长度、token、category、hash、IDs 和 timing。
2. 需要 Langfuse 原文的环境必须显式 opt-in，并配置采样、脱敏和 retention；不能因为 tracing 开启就默认上传完整 history/output。
3. 输入敏感扫描发生在 telemetry content capture 之前。是否保留被拦截原始 query 作为产品数据必须单独确认；默认只保留脱敏内容或安全事件摘要。
4. provider reasoning 使用结构化字段时只统计时间和 token，不向用户或普通消息持久化；兼容 `<think>` 的 provider 输出必须在 server 端剥离。
5. `original_unsafe_output` 默认改为 hash、category、命中规则和脱敏摘要。若训练 badcase 确需原文，应写入单独加密、短 retention、严格 RBAC 的存储。
6. 流式 output 增加 rolling safety buffer 或按句发布：增量检测通过后才发送；结束时再做完整输出扫描。
7. 外部 Web chunk 进入 RAG 前执行 injection/sensitive scan，把风险写入 `meta_info` 并在 Prompt 中逐 chunk 标记。
8. 保留轻量规则作为第一层快速门禁；生产发布前增加更可靠的内容安全分类器，并定义 timeout/failure 时 fail-open 还是 fail-closed。
9. 为安全拒答、RAG 拒答、Credits 失败和系统失败使用不同稳定 outcome/error code，避免所有情况共用“成功返回一段拒答文本”。

### 8.3 验证

需要建立不包含真实 secret 的 synthetic fixture 集：API key、密码、手机号、邮箱、身份证样例、prompt injection、多语言变体、字符分隔和跨 chunk 拼接。

| 场景 | 预期 |
| --- | --- |
| 默认 telemetry 配置 | Langfuse/trace 不含 query、history、output 原文 |
| `<think>` / structured reasoning | SSE、DB、citation 和普通 telemetry 均不含 reasoning 原文 |
| 敏感模式跨多个 chunk | 在危险内容发送前拦截或缓冲，不把完整敏感值暴露给用户 |
| output guardrail 触发 | 普通 message metadata 不保存原始 unsafe output |
| 恶意 Web chunk | 标记 injection risk，不被当成系统指令执行 |
| sanitizer 失败 | 按明确策略丢弃 content capture，不阻断核心 metrics/trace 关联 |
| 安全分类器 timeout | 按配置的 fail-open/fail-closed 行为执行并记录稳定事件 |

Focused 验证建议：

```bash
uv run pytest \
  tests/unit/workflows/test_worker_generation_guardrails.py \
  tests/unit/observability/test_langfuse_generation.py -q
make qa-test-component
```

### 8.4 完成标准与依赖

WS4 的数据盘点与 sanitizer 设计可以提前；完整流式安全实现依赖 WS3 的 versioned event/terminal contract。完成标准：

- 默认观测不保存或外发完整对话内容。
- reasoning 与原始 unsafe output 不进入普通用户数据路径。
- 输入、Web context、流式输出和最终输出都有明确安全边界。
- 安全机制的降级行为、retention 和 owner 有文档与测试证明。

## 9. WS5 — RAG 模式、历史、引用与评测

### 9.1 当前情况与依据

当前优势是模块边界已经形成：Planner、KB/Web retrieval、rerank、evidence policy、context budget 和 citation validator 可分别测试。主要缺口是产品语义和质量门：

- Evidence Policy 在无 KB、外部证据不足时明确“允许 LLM 自由回答”（[`rag_evidence_policy.py`](../../backend/services/rag_evidence_policy.py#L63)）。对 `web_only` 而言，这会把实时检索请求静默降级成模型参数知识。
- 外部检索、KB 检索和 rerank 异常均降级为空结果或原始排序，失败原因主要写日志（[`worker_rag_orchestrator.py`](../../backend/application/chat/worker_rag_orchestrator.py#L408)）；调用方难以区分“确实无结果”和“基础设施失败”。
- 会话消息按时间升序再 `limit`（[`chat_repo.py`](../../backend/repositories/chat_repo.py#L178)），默认 fetch limit 为 2000；超长会话获取的是最旧 2000 条，不是最近消息。
- history projection 只检查 role/content，不过滤 message status（[`history_projection.py`](../../backend/application/chat/history_projection.py#L9)），FAILED assistant 错误文本可能进入后续 Prompt。
- Citation Validator 明确只做正则 ID 校验，不判断 claim 是否被证据支持（[`citation_validator.py`](../../backend/services/citation_validator.py#L1)）。
- Context Builder 先为所有 retrieved chunks 构建 `search_context`，随后按 token budget 缩减 `context_chunks`（[`chat_context_builder.py`](../../backend/ai/core/chat_context_builder.py#L147)）；citation valid IDs 可能包含没有实际进入最终 Prompt 的 chunk。
- Eval 工具已覆盖 Planner、Retrieval 和 Answer 三层（[`evals/README.md`](../../evals/README.md#L1)），但仓库只有 4 条 sample dataset，API/Ragas 评测为 opt-in，不是质量门。

### 9.2 推荐修改

先批准模式契约：

| `context_mode` | 推荐行为 | 无证据/故障行为 |
| --- | --- | --- |
| `off` | 明确使用模型自身知识 | 正常模型回答，metadata 标记 `parametric` |
| `kb_only` | 只使用绑定 KB | 无有效证据则拒答；KB 故障明确 `degraded/failed` |
| `web_only` | 只使用外部 Web 证据 | 无证据或 provider 故障则明确拒答/失败，不静默自由回答 |
| `auto` | Planner 在 KB、Web、模型知识间选择 | 可以降级，但必须返回 `degraded=true`、实际 source 和 reason |
| KB + Web | KB 为主，Web 补充时效信息 | 两个 source 分别报告 status，不合并成一个空列表 |

如果产品希望 `web_only` 在失败时仍允许模型自由回答，应把该模式改名为 `web_preferred`，避免名称与行为相冲突。

实施步骤：

1. 引入 typed `RetrievalOutcome`：至少包含 `source`、`status=success|empty|degraded|failed`、`chunks`、`reason`、`provider`、`latency_ms`。
2. Planner、KB、Web、rerank 的 outcome 汇总到 `search_context` 和 trace；流式 step 使用 `degraded/error` 呈现，不只写 warning log。
3. 调整历史查询：先按时间倒序取最近 N 条，再在内层/应用层恢复正序；只纳入有效 user message 与 `SUCCESS` assistant message。
4. Context Builder 返回 `prompt_used_ref_ids`，Citation Validator 只接受真正进入最终 Prompt 的 refs。
5. 保留运行时 marker/ID 校验；claim-evidence faithfulness 放到离线 eval，不在主请求链路增加昂贵的逐句 LLM judge。
6. 建立版本化真实 dataset，覆盖精确事实、无答案拒答、时效问题、KB/Web 冲突、长会话、FAILED 历史、prompt injection、多语言和引用忠实度。
7. 将确定性的 Planner/retrieval regression 放入常规验证；带外部 LLM judge 的 answer eval 放到 scheduled/release/manual gate。
8. 第一份 baseline 只记录指标，不立即制定武断阈值；至少经过一次稳定复跑后，再批准 regression budget 和 merge/release gate。

### 9.3 验证

| 维度 | 指标/断言 |
| --- | --- |
| Planner | `should_use_rag`、mode、source、rerank decision accuracy |
| Retrieval | hit@k、recall@k、MRR、empty/error 分类准确率 |
| Refusal | must-refuse accuracy、false refusal、`web_only` failure correctness |
| Answer | faithfulness、answer relevancy、可选 correctness |
| Citation | marker validity、prompt-used ref coverage、unsupported claim rate（离线） |
| History | 超过 2000 条仍保留最近轮次，FAILED 内容不进入 Prompt |
| Degradation | provider fault 与真实 empty 在 API、SSE、trace 中可区分 |

Focused 验证建议：

```bash
uv run pytest \
  tests/unit/workflows/test_worker_generation_rag.py \
  tests/unit/workflows/test_worker_generation_citation.py \
  tests/unit/ai/test_chat_context_builder.py -q
make qa-eval-rag EVAL_DATASET=evals/dataset.sample.jsonl
make qa-eval-api EVAL_DATASET=evals/dataset.sample.jsonl
```

正式验收不能继续使用 sample dataset；上面的命令仅证明工具链可运行，质量结论必须使用经评审的真实版本化 dataset。

### 9.4 完成标准与依赖

WS5 的 dataset 整理可立即并行；涉及 message/request 查询和主链路 outcome 的修改依赖 WS1。完成标准：

- 四种 mode 的正常、empty、degraded、failed 行为均有契约测试。
- 长历史、FAILED history 和 prompt-used refs 缺陷被修复。
- API/前端可识别实际使用的 source 与 degradation reason。
- 真实 dataset、baseline、报告对比和阈值批准流程可重复执行。

## 10. WS6 — Worker generation 结构重构

### 10.1 当前情况与依据

[`worker_generation_workflow.py`](../../backend/application/chat/worker_generation_workflow.py#L1)当前约 1014 行，另有约 671 行的 [`worker_rag_orchestrator.py`](../../backend/application/chat/worker_rag_orchestrator.py#L1)。项目已经抽出：

- `WorkerRAGOrchestrator`
- `WorkerPersistenceHandler`
- `WorkerGuardrailHandler`
- `WorkerStreamPublisher`

因此问题不是“所有逻辑都在一个类”，而是 stream/non-stream 仍分别编排 Guardrail、RAG refusal、model route、LLM、citation、token、Credits 和持久化；业务 success、transport success 与 persistence success 也没有统一 result contract。

如果在 WS1–WS5 前直接按文件行数拆分，会把不一致状态协议复制到更多模块，并提高后续修复成本。

### 10.2 推荐修改

重构目标是统一生命周期，而不是追求任意行数。建议最终围绕四个阶段：

```text
Preparation
  input guardrail -> RAG -> prompt -> model route

Execution
  provider stream/non-stream call -> raw usage/result

Finalization
  reasoning removal -> output safety -> citation
  -> Credits settlement -> durable terminal commit

Delivery
  stream event adapter | non-stream response adapter
```

实施步骤：

1. 补 characterization tests，冻结 WS1–WS5 已批准的输入、输出、状态、error code、usage 和 event sequence。
2. 引入统一 `GenerationOutcome` / terminal contract，区分 `answered`、`refused`、`blocked`、`failed`、`cancelled`。
3. 先抽取共享 Finalizer，使 stream/non-stream 共用 reasoning removal、guardrail、citation、Credits 与 durable commit。
4. 再抽取共享 Preparation，使 input guardrail、RAG、Prompt 和 model routing 只实现一次。
5. 保留两个薄 Execution/Delivery adapter：stream 负责 chunk/event，non-stream 负责完整 provider response；两者都返回同一个 outcome。
6. 将 metrics 构造收敛到结构化对象，避免 Web、Worker 和 Langfuse 对同一 timing/token 字段重复计算或使用不同来源。
7. 在所有生产者切换到 versioned payload 后，删除 Worker task 的旧 positional compatibility。
8. 不引入万能 `BaseWorkflow`；组件只围绕真实的两个以上调用点抽象。

重构必须继续满足：

- Web 不 import `backend.worker`。
- Web -> Worker 只经过 `AbstractTaskDispatcher`。
- Worker 不依赖 `backend.api`。
- endpoint -> workflow/service -> repository -> ORM 边界不被打穿。
- DB transaction 与 external I/O 的所有权保持明确。

### 10.3 验证

先做行为等价，再看结构指标：

| 验证面 | 要求 |
| --- | --- |
| State | 同一输入下 stream/non-stream terminal outcome 一致 |
| Credits | token source、reservation、settlement 和 usage record 一致 |
| Safety | input/output decisions 与 WS4 基线一致 |
| RAG | mode、refs、degradation metadata 与 WS5 基线一致 |
| Stream | event 顺序、terminal、disconnect recovery 不回退 |
| Architecture | import boundary、layer dependency 检查通过 |
| Performance | 首 token、总延迟、tokens/s 无未经批准的明显回退 |

最终验证建议：

```bash
make qa-boundaries
make qa-layer-deps
make qa-no-while-true
make flow-fast
make flow-ci
make flow-pr-preflight
```

`make flow-pr-preflight` 需要本地 Postgres 与 Redis；真实 TaskIQ、stream 和故障注入结果应随 PR 记录，不用单元测试替代。

### 10.4 完成标准与依赖

WS6 依赖 WS1–WS5 全部达到 validated checkpoint。完成标准：

- stream/non-stream 共用 Preparation、Finalization 和 terminal contract。
- 重构没有改变已批准的产品语义或恢复策略。
- 全量静态、单元、组件、集成、前端和性能对比通过。
- 删除的兼容路径已确认没有旧部署或排队任务依赖。

## 11. 跨工作流验证策略

每个工作流都按由窄到宽的证据层级验收：

| 层级 | 内容 | 用途 |
| --- | --- | --- |
| V0 | 静态证据、状态表、migration/data audit、配置检查 | 确认设计与现状，不证明运行行为 |
| V1 | focused unit / contract tests | 证明单个状态迁移、policy 和 adapter |
| V2 | Postgres、Redis、TaskIQ、API component、frontend tests | 证明跨边界契约 |
| V3 | `make flow-fast`、`make flow-ci`、`make flow-pr-preflight` | 仓库级回归和架构门禁 |
| V4 | Worker kill、Redis fault、disconnect、真实 eval、性能对比 | 证明恢复、质量和运行时语义 |

最低门禁矩阵：

| 工作流 | V0 | V1 | V2 | V3 | V4 |
| --- | --- | --- | --- | --- | --- |
| WS1 | 必须 | 必须 | 必须 | 必须 | 并发/Redis fault |
| WS2 | 必须 | 必须 | 必须 | 必须 | Worker kill/timeout |
| WS3 | 必须 | 必须 | 必须 | 必须 | disconnect/Web restart |
| WS4 | 必须 | 必须 | 必须 | 必须 | telemetry/retention 审核 |
| WS5 | 必须 | 必须 | 必须 | 必须 | 真实 dataset/eval |
| WS6 | 必须 | 必须 | 必须 | 必须 | 性能与完整主链路对比 |

通用验收原则：

1. 每个 bugfix 先有能失败的 focused regression，再修改行为。
2. Redis、TaskIQ 和 DB 的跨边界结论不能只靠 mock 单测证明。
3. migration 必须有 upgrade、downgrade、旧数据审计和生产 rollout 顺序。
4. 任何自动 retry 必须在 fencing 与 Credits 幂等验证后启用。
5. RAG LLM-as-Judge 不替代确定性的 mode、retrieval 和 citation contract tests。
6. 文档中的 proposed command 只有在实际运行并保存结果后，才能把 checkpoint 标为 validated。

## 12. 推荐 PR 与 checkpoint 拆分

一个工作流不必等于一个 PR。建议采用以下顺序，避免 giant PR：

| PR | 主要范围 | Checkpoint |
| --- | --- | --- |
| PR 1 | WS1 contract tests、generation request schema/repository/migration | `request-state-model-implemented` |
| PR 2 | WS1 Web/Worker CAS、idempotency retry、Credits reservation/settlement、Redis best-effort | `request-consistency-validated` |
| PR 3 | WS2 dispatcher 拆分、deadline、reconciler、真实 TaskIQ integration | `task-recovery-validated` |
| PR 4 | WS3 versioned event、terminal、disconnect recovery、frontend status | `stream-contract-validated` |
| PR 5 | WS4 sanitizer、reasoning removal、unsafe retention、Web chunk scan | `content-safety-validated` |
| PR 6 | WS5 mode/outcome、recent history、prompt-used refs | `rag-contract-validated` |
| PR 7 | WS5 真实 dataset、baseline、report comparison 与 gate 策略 | `rag-baseline-validated` |
| PR 8+ | WS6 分阶段抽取 Finalization、Preparation、Delivery adapter | `worker-refactor-validated` |

每个 checkpoint 只在本工作流 focused validation 与必要的跨边界验证都通过后更新；“代码已合并”不自动等于 validated。

建议 rollout 顺序：

1. Schema/migration 先向后兼容部署，不立即删除旧字段或旧 payload。
2. Worker 先支持新旧 payload，再部署 Web producer。
3. 所有 Web 实例切换后观察队列 drain，再删除旧 compatibility。
4. Stream protocol 采用 version 字段渐进切换，前端先兼容新旧 terminal。
5. Guardrail/Langfuse content capture 先以安全默认关闭上线，再按环境显式启用。
6. RAG mode 行为变化应有 feature flag 或明确 release note，避免静默改变拒答率。
7. WS6 只做内部结构变更，不与 migration、mode 语义变化放在同一 PR。

## 13. 决策门与推荐默认值

以下问题需要在对应工作流实施前确认。表中同时记录本计划的推荐默认值：

| 决策 | 推荐 | 原因 |
| --- | --- | --- |
| generation identity 放在哪里 | 新增 `chat_generation_requests` | Message 内容与执行状态生命周期不同，后续需要 task/attempt/lease/heartbeat |
| 幂等唯一范围 | `(user_id, client_request_id)` | 与当前 Redis key 和跨用户隔离语义一致 |
| Credits 何时确认 | LLM 前 reserve，terminal 前 settle | 避免生成/展示后才发现余额不足 |
| Redis marker 失败 | DB success 保持，记录告警并恢复缓存 | Cache/notification 失败不能逆转 durable transaction |
| Task retry | fencing 后才启用 | 没有 lease 时自动 retry 会产生并发旧 Worker |
| HTTP disconnect | 默认继续 Worker | 网络断连不等于用户取消，结果可持久化后恢复 |
| 第一阶段是否支持 stream replay | 否，先用 DB terminal recovery | 先解决状态一致性，避免一次引入完整 Redis Streams 协议 |
| `web_only` 无证据 | 明确拒答/失败 | 防止把模型参数知识伪装成实时 Web 答案 |
| Langfuse content capture | 默认关闭 | 数据最小化；需要原文时显式 opt-in、采样和 retention |
| unsafe output 原文 | 不进入普通 message metadata | 降低敏感内容长期留存和普通读取面 |
| RAG 阈值 | 首次真实 baseline 后批准 | sample dataset 不能支持可靠门槛 |

若某项选择与推荐不同，应在 PR 或后续 durable work item 中记录原因、替代风险和新增验收条件。

## 14. 主要风险与回滚点

| 风险 | 缓解/回滚 |
| --- | --- |
| 新 request 表与旧消息状态双写漂移 | 过渡期增加一致性断言和监控；先只读对比，再切换事实源 |
| migration 遇到旧数据不满足约束 | 部署前 data audit；先 backfill/修复，再创建唯一索引 |
| Credits reservation 改变用户体验 | feature flag 或小流量 rollout；保留旧 final-only 结算开关作为短期回滚 |
| Reconciler 误判长任务 | heartbeat + lease + 宽限期；不在无 fencing 情况下重投 RUNNING task |
| 新 SSE protocol 与旧前端不兼容 | versioned event；前端先兼容，后端后切换，保留短期旧 parser |
| Content sanitizer 降低排错信息 | 保留 IDs、hash、长度、category、timing；受控环境短期 opt-in 原文 |
| `web_only` 改为拒答导致拒答率上升 | feature flag、真实 eval、release note 和监控拒答率 |
| 重构混入行为变化 | WS6 独立 PR；characterization + baseline diff；必要时按抽取步骤逐个回滚 |

## 15. 证据索引

- HTTP 与 Web workflow：[`chat_api.py`](../../backend/api/v1/endpoint/chat_api.py)、[`web_nonstream_workflow.py`](../../backend/application/chat/web_nonstream_workflow.py)、[`web_stream_workflow.py`](../../backend/application/chat/web_stream_workflow.py)。
- 会话、幂等与历史：[`session_orchestrator.py`](../../backend/application/chat/session_orchestrator.py)、[`history_projection.py`](../../backend/application/chat/history_projection.py)、[`chat_repo.py`](../../backend/repositories/chat_repo.py)。
- Dispatcher 与 TaskIQ：[`task_dispatcher.py`](../../backend/infra/task_dispatcher.py)、[`task_broker.py`](../../backend/infra/task_broker.py)、[`llm_tasks.py`](../../backend/worker/tasks/llm_tasks.py)。
- Worker 编排与持久化：[`worker_generation_workflow.py`](../../backend/application/chat/worker_generation_workflow.py)、[`worker_persistence_handler.py`](../../backend/application/chat/worker_persistence_handler.py)、[`worker_stream_publisher.py`](../../backend/application/chat/worker_stream_publisher.py)。
- RAG：[`worker_rag_orchestrator.py`](../../backend/application/chat/worker_rag_orchestrator.py)、[`rag_planning_service.py`](../../backend/services/rag_planning_service.py)、[`rag_evidence_policy.py`](../../backend/services/rag_evidence_policy.py)、[`chat_context_builder.py`](../../backend/ai/core/chat_context_builder.py)、[`citation_validator.py`](../../backend/services/citation_validator.py)。
- 安全与观测：[`chat_safety_metadata.py`](../../backend/services/chat_safety_metadata.py)、[`safety_scanner.py`](../../backend/services/safety_scanner.py)、[`langfuse_utils.py`](../../backend/observability/langfuse_utils.py)。
- 前端流：[`chat-stream.ts`](../../frontend/apps/admin/src/streams/chat-stream.ts)、[`use-chat-controller.ts`](../../frontend/apps/admin/src/features/chat/use-chat-controller.ts)。
- 测试与评测：[`test_task_dispatcher.py`](../../tests/unit/infra/test_task_dispatcher.py)、[`test_taskiq_integration.py`](../../tests/integration/test_taskiq_integration.py)、[`evals/README.md`](../../evals/README.md)。

## 16. 最终建议

第一实施检查点只处理 WS1，不同时重构 Worker。WS1 开始编码前，应先评审并冻结：generation request schema、状态机、Credits reservation/settlement、attempt/lease 语义和故障测试矩阵。

WS1 validated 后依次推进 Task 恢复和流式终态；RAG dataset 可以并行准备，但任何主链路重构都应等 WS1–WS5 的外部行为和验证基线稳定。这样能把当前“局部模块化、全局协议不完整”的状态，逐步收敛成可恢复、可计费、可解释、可评测的产品主链路。
