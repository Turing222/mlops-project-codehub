# 工作项计划：T1-Lite 最低告警与内容安全默认值

> 机读状态（`status`、`workstreams`、`current_checkpoint`、`next_choices`、
> `open_decisions`）只保存在 `manifest.yaml`，并以它为准。
> 本文件只记录稳定叙事：为什么做、范围是什么、取舍是什么。

## 目标

在不扩展短信生产化、灾备恢复和完整观测平台的前提下，补齐受控内测真正需要的两条基础停止线：关键故障能够产生有限、可送达、可行动的告警；用户内容、模型 reasoning 和 unsafe 原文默认不进入常规观测或普通业务 metadata。该工作项追求的是一个边界清楚的 T1-Lite，不借精简范围声明完整生产就绪。

## 对话结论

- T1-5 拆成 `T1-5A — 最低告警闭环` 与 `T1-5B — 恢复实证`；本工作项只承接 T1-5A。
- T1-5B 不创建空壳 workstream。RDS / S3 恢复、生产中断演练、EC2 / Tunnel / secret 重建及 RPO / RTO 统一 deferred；恢复该范围时另建 `production-recovery-evidence`。
- T1-6 保留为当前范围，但用“默认不采集内容 + 边界处移除 reasoning + synthetic fixture 回归”作为最小闭环，不建设通用内容治理平台。
- 已完成的 SMS rate limit、验证码失败 lockout 和真实 client IP 防护继续生效；不接真实 SMS provider，不补短信生产验收、专项告警或恢复。
- `security-operability-baseline` 的原 WS4 不再同时承担 CSP 和告警。最低 AWS 告警迁入本工作项，CSP enforcement 留给 T2-6。
- T1-4 的 recovery / heartbeat / outbox 结构化事件是任务告警事实源；不再通过自由文本推断任务状态，也不重建第二套任务状态机。
- 结束时只能声明 `T1-Lite validated for controlled internal use`，不能声明完整 T1-5 validated、灾备就绪、任务绝不丢失或高可用。

## 范围边界

| 范围 | 当前交付 | 明确不做 |
| --- | --- | --- |
| T1-5A 告警 | API、任务、队列、端到端存活、Redis 与日志 dead-man；一次 CloudWatch -> Alarm -> SNS 送达 | dashboard、全量 SLO、IaC 平台、所有日志字段统一 |
| T1-6 内容安全 | 生产禁止内容采集、unsafe metadata 安全摘要、reasoning 剥离、泄漏回归 | 通用 sanitizer、完整 retention / sampling / access 平台、高级分类器 |
| SMS | 保留已经交付的 abuse 防护 | provider 接入、真实短信验收、专项告警和恢复 |
| T1-5B 恢复 | 只记录 deferred 边界 | RDS / S3 / Redis / Worker / EC2 / Tunnel / secret 恢复实证及 RPO / RTO |

## 实施原则

- 只标准化首批 alarm filter 实际消费的事件，顶层字段优先采用 `event`、`error_code`、`task_name`、`job_id`、`generation_request_id`、`attempt`、`duration_ms`；不存在的字段不伪造。
- 告警必须包含 signal source、filter / measurement、threshold、window、receiver 和最短处置说明；单独存在 metric 或脚本不算闭环。
- Worker 与 Scheduler 使用一条端到端 canary 证明 scheduler -> broker -> worker -> structured log 链路，而不是两个只能证明进程仍在的本地心跳。
- queue depth 从 broker Redis 读取；oldest age 使用 durable DB 中可解释的 pending / due / lease 事实，不解析不稳定的 TaskIQ 私有 payload。
- Web 继续只通过 `AbstractTaskDispatcher` 派发，不导入 `backend.worker`，不直接调用 `.kiq()`；probe 遵守现有 web / worker 边界。
- 内容安全优先在数据进入 telemetry、SSE 和普通持久化前阻断，不依赖事后清洗日志。
- 受控信号验证不得制造恢复演练或破坏生产数据；优先使用明确标记的 synthetic event 或可逆的短时阈值测试。

## Workstream 拆分理由

### WS1 — Persist the approved T1-Lite scope and transfer legacy WS4 ownership

- Scope：把裁剪判断写入后端路线图；将旧 `security-operability-baseline` WS4 的最低告警职责移交到本工作项，并保留其前三个已交付范围的历史语义。
- Reason：大路线图、历史 work item 和当前执行计划必须只有一个告警 owner，且不能把 deferred 能力误记为完成。
- Expected effect：后续恢复时能直接判断当前该做什么、什么不属于本轮，以及完成后的声明上限。

### WS2 — Freeze the minimum alert signal and field contract

- Scope：冻结首批 signal inventory、稳定事件名、顶层 JSON 字段、测量方式、阈值窗口、SNS receiver 和 runbook 入口；逐项映射现有生产者与 CloudWatch filter。
- Reason：先固定消费者所需合同，才能避免为了“统一日志”扩大到全仓重构，也能及时发现现有 filter 与字段不匹配。
- Expected effect：每个告警都能从代码事件追溯到 metric、Alarm 和处置动作；未纳入首批告警的日志无需同步改造。

### WS3 — Normalize critical structured events and task lifecycle fields

- Scope：收敛 API 5xx / latency、T1-4 terminal failure / outbox dead、Redis eviction / restart 等关键 producer；确保 filter 所需字段位于 JSON 顶层且不包含用户原文。
- Reason：CloudWatch metric filter 依赖稳定机器字段，自由文本和嵌套 extra 容易导致静默漏报。
- Expected effect：告警 filter 能用固定字段匹配，事件仍保留 request / task / attempt 关联，并通过聚焦测试锁定格式。

### WS4 — Add a bounded backlog and end-to-end liveness probe

- Scope：增加有超时、无常驻 busy loop 的 probe，输出 broker queue depth、durable oldest pending age 和 canary trace；由现有 Scheduler 派发，经 Redis / Worker 执行并产生结构化完成事件。
- Reason：进程级 heartbeat 无法证明 broker 与 worker 的真实链路；单看 queue depth 也无法区分短时流量与持续阻塞。
- Expected effect：一个 dead-man window 可以识别 Scheduler、broker、Worker 或日志链路中断，backlog 信号可以区分深度和等待时间。

### WS5 — Configure the minimum CloudWatch Alarm and SNS delivery set

- Scope：让 CloudWatch metric filters 与 WS2 / WS3 事件合同一致，建立最小 alarms 与 SNS email receiver，并用一次非恢复型受控信号完成发送、接收确认和证据记录。
- Reason：T1-Lite 需要证明故障会触达到人；仅有脚本成功、Alarm 配置或未确认订阅都不构成告警闭环。
- Expected effect：首批关键故障具有有界检测时间、明确接收人和最短处置动作，同时不引入自托管 Alertmanager 或 IaC 工程。

### WS6 — Enforce content-safe telemetry and unsafe metadata defaults

- Scope：生产环境拒绝或忽略 `capture_content=true`，Langfuse / tracing 默认不写 query、history、output；unsafe metadata 仅允许 hash、category、matched rule 与脱敏摘要。
- Reason：当前风险发生在普通数据路径，单靠访问控制或后续 retention 不能撤回已经外发、持久化的原文。
- Expected effect：常规 telemetry 和普通 message metadata 在默认配置及生产配置下都不含用户内容或 unsafe 原文。

### WS7 — Strip provider reasoning and add synthetic leak regressions

- Scope：在 provider 输出进入 SSE、普通持久化和 telemetry 前移除 reasoning / `<think>`；加入 synthetic secret / PII fixtures，覆盖 query、history、output、reasoning 与 unsafe raw output。
- Reason：多个下游各自清理容易遗漏；边界处剥离并对所有出口做负向断言更容易形成稳定安全合同。
- Expected effect：用户可见答案保持正常，但内部 reasoning 和测试秘密不会出现在 SSE payload、数据库 metadata 或观测记录中。

### WS8 — Validate the T1-Lite alerting and content-safety acceptance matrix

- Scope：执行告警链路、dead-man / backlog、关键事件格式和内容泄漏矩阵；记录 receiver 确认、测试命令、证据位置、已知限制和最终状态措辞。
- Reason：该工作项包含本地代码、AWS 配置和负向安全断言，任何单一测试层都不足以证明整个完成链。
- Expected effect：交接材料能够证明 T1-Lite 的实际边界，并明确指出未验证的恢复能力和正式生产条件。

## 最低告警合同

| Signal | 最小事实源 | T1-Lite 验收方式 | 首要动作 |
| --- | --- | --- | --- |
| API 5xx | Nginx / API 结构化状态字段 | 受控 5xx 进入 metric 并触达 receiver | 按 request / trace ID 定位 endpoint 与异常 |
| API latency | `request_time` 或统一 `duration_ms` | 可控慢请求越过固定窗口阈值 | 区分 upstream、DB 与外部 provider 延迟 |
| Queue backlog | broker queue depth + DB oldest pending age | depth 或 oldest age 持续越界 | 查 scheduler、Redis、Worker 与 durable due 状态 |
| End-to-end liveness | scheduler 派发 canary，Worker 写完成事件 | 完成事件超过 dead-man window 未出现 | 沿 scheduler -> broker -> worker -> logs 逐段检查 |
| Terminal task failure | T1-4 `chat_generation_recovery_failed`、`knowledge_outbox_dead` 等稳定事件 | ERROR 事件按稳定 `error_code` 聚合 | 查 PostgreSQL 事实状态，使用受控 operator / retry 入口 |
| Redis risk | eviction、OOM / command failure、restart 相关信号 | 增量或缺失状态越过固定窗口 | 区分 cache Redis 与 TaskIQ Redis，禁止盲目重放 |
| Log dead-man | 约定的周期 canary / heartbeat metric | 指定时间窗无新数据 | 先验证采集链，再判断服务是否真实中断 |

告警阈值不追求一次性“最优”。首版应采用有说明的保守固定值，并把连续窗口、缺失数据策略与抑制方式写入配置或 runbook；完成受控内测观察后再调优。T1-Lite 不用 RDS backup alarm 代替恢复实证，也不把 AWS 主机资源告警扩展成完整容量治理。

## 内容泄漏验收矩阵

使用互不相同、可精确搜索的 synthetic marker 分别代表 query、history、output、provider reasoning 和 unsafe raw output。测试应在调用后搜索实际 SSE frame、普通 message / metadata 持久化对象、结构化日志和 tracing recorder 参数，而不是只断言配置值。

| Marker 类型 | SSE | 普通持久化 | telemetry / logs |
| --- | --- | --- | --- |
| query / history | 不因 telemetry 回显 | 不新增副本 | 不出现原文 |
| ordinary output | 仅作为正常用户答案按产品合同输出 | 只按现有业务合同保存 | 不被 tracing 捕获原文 |
| provider reasoning / `<think>` | 不出现 | 不出现 | 不出现 |
| unsafe raw output | 不出现原文 | 只保存安全摘要字段 | 不出现原文 |

测试失败时应报告 marker 出现在哪个出口，但不能把完整 fixture 重新写入普通日志。hash 只用于关联同一 synthetic 样本，不能被描述为可逆恢复手段。

## 建议实施批次

1. 合同批次：完成 signal inventory、字段映射、阈值窗口和内容出口盘点，只修改文档与失败测试基线。
2. 并行基础批次：一条实现线完成关键 structured events 与 probe；另一条实现线完成 `capture_content` 生产保护、unsafe metadata 和 reasoning 边界。
3. 闭环批次：配置最小 CloudWatch filters / alarms / SNS，补齐泄漏回归，并在非恢复型受控场景记录 receiver 确认。
4. 交接批次：运行聚焦测试和仓库质量门，回填证据、限制和 runbook；只在完整 completion chain 成立后更新机读 checkpoint。

每个批次应保持小范围可回滚。告警代码与 AWS 配置可以分开提交，但在 receiver 确认前不能把告警 workstream 视为验收完成；内容安全实现与负向泄漏测试应在同一交付序列内完成。

## 验证策略

- 文档阶段：校验 work-item schema、Markdown 引用与仓库文档质量门。
- 代码阶段：为结构化字段、生产 content-capture guard、unsafe metadata allowlist 和 reasoning strip 增加 focused unit tests。
- 集成阶段：使用真实 PostgreSQL / Redis 的非破坏性测试验证 backlog 与 canary 事实源，保持 T1-4 的 attempt / lease / CAS 语义不变。
- AWS 阶段：记录 metric filter、Alarm 状态变化、已确认 SNS subscription、实际送达时间和接收人确认；秘密、邮箱地址和账号 ID 不写入仓库。
- 最终阶段：运行相关 backend unit / component、config、import boundary、typecheck 与 docs gates；已知仓库基线问题单独记录，不用本工作项顺手扩修。

## Checkpoint 证据

### WS2 — Minimum alert contract implemented（2026-07-17）

- `deploy/monitoring/alarms-cloudwatch.md` 已冻结首批 8 类 signal 的 producer、JSON filter / measurement、metric statistic、默认 threshold、连续 window、missing-data 策略、SNS receiver 合同与最短 runbook。
- API 采用 `event=api_request_completed` 的 `status_code` / `duration_ms`；backlog 与 dead-man 采用每分钟 `t1_lite_heartbeat_completed`；terminal failure 直接消费 T1-4 stable event，不解析自由文本。
- queue depth 只作为 TaskIQ Redis 传输层事实；oldest pending 明确回到 PostgreSQL generation / TaskJob / outbox due / lease facts。Redis 风险按 role 输出 eviction delta 与 restart observation。
- 非恢复型送达验证使用独立 `t1_lite_synthetic_alarm`，不能代替 receiver 人工确认，也不能被解释为 T1-5B recovery evidence。
- 该 checkpoint 只表示消费者合同已实现；producer、CloudWatch 资源、实际 SNS 送达与内容安全仍须后续 checkpoint 证明。

### WS3–WS4 — 关键 producer 与端到端 heartbeat 已实现并本地验证（2026-07-17）

- API 响应现在以顶层 `event=api_request_completed`、`http_request_id`、规范化 route、`status_code`、`duration_ms` 和 5xx `error_code` 输出；测试证明 query marker 不进入结构化日志。
- Chat terminal / recovery 和 Knowledge outbox dead 事件已固定 `task_name`、真实 `attempt` / `job_id`、`error_code` 和实测 `duration_ms`；不存在的 attempt 或 job 字段没有伪造。
- `OperabilityProbeService` 通过 repository / UoW 顺序读取 Chat generation、TaskJob 和 outbox 的 durable due / lease 事实；queue depth 只从 TaskIQ Redis 的公开 queue key 读取。真实 PostgreSQL 集成暴露并修复了共享 `AsyncSession` 不能并发查询的约束。
- 每分钟 heartbeat 已注册到现有 Scheduler 和 Worker module 列表。集成测试实际调用 `LabelScheduleSource` / `TaskiqScheduler` 入队，由独立 Worker 进程经专用 Redis 消费，最后从 JSONL 日志解析到 `t1_lite_heartbeat_completed`。该链路同时读取迁移后的 PostgreSQL、业务 Redis 与 TaskIQ Redis。
- 聚焦命令结果：alert / repository / scheduler / producer 单测 `59 passed`，对应 `tests/unit/config/test_t1_lite_monitoring.py`、`tests/unit/middleware/test_tracing.py`、`tests/unit/repositories/test_chat_repo.py`、`tests/unit/repositories/test_task_outbox_repo.py`、`tests/unit/repositories/test_task_repo.py`、`tests/unit/services/test_operability_probe.py`、`tests/unit/worker/test_operability_tasks.py`、`tests/unit/worker/test_scheduler_entrypoint.py`、`tests/unit/workflows/test_chat_generation_recovery.py`、`tests/unit/workflows/test_knowledge_outbox_relay.py`；`bash scripts/qa/run_with_smoke_env.sh uv run pytest -q tests/integration/test_t1_lite_operability_probe.py` 为 `2 passed`。集成测试前置条件是 `docker-compose.db.yml` 的 `postgres` / `redis-cache` / `redis-taskiq` 三个服务在运行，否则 TaskIQ Redis `6380` 直接 ConnectionError。集成测试不创建业务数据、不派发业务任务，只清理本测试的 result / observation keys。
- 该 checkpoint 真实关闭 WS3 与 WS4，但不声称 CloudWatch 资源已应用或 SNS 已送达；WS5 仍保持 `in_progress`。

### WS6–WS7 — 内容安全默认值与 synthetic 泄漏矩阵已实现（2026-07-17）

- 新增 `TELEMETRY_CAPTURE_CONTENT=false` 默认值；`APP_ENV=prod|production` 与 `true` 同时出现时 Settings 直接拒绝启动，因此不存在生产原文 opt-in 路径。
- Chat LLM、RAG planner 与 README analyzer 的 Pydantic AI instrumentation 都显式设置 `include_binary_content=false`，并把 `include_content` 绑定到 `TELEMETRY_CAPTURE_CONTENT`（默认 false，生产由 Settings validator 强制 false）；因此生产不存在原文采集路径，非生产仍可显式 opt-in。Worker 任务不再把 generation payload 或 output 交给 Langfuse recorder。Langfuse 帮助层仍有第二层默认拒绝，异常状态只写通用 `generation_failed`。
- provider / routing / RAG / embedding / rerank 异常路径只保留 `error_type`、稳定 `error_code` 与必要 status，不再把第三方 exception message、HTTP body 或 traceback 送入常规日志 / error metadata；业务 span 异常同样只保留类型与通用错误状态。
- unsafe output 的普通 message metadata 已升级为 schema v2，只保留 SHA-256、category、规则名和长度型脱敏摘要；普通 answer 不再在 metadata 里制造第二份 output。
- 流式 `StreamingReasoningFilter` 可处理任意 chunk 边界上拆开的大小写 `<think>...</think>`，未闭合 reasoning 也 fail closed；非流式路径使用同一规则。只有剔除后的可见答案可进入 guardrail、citation、Redis chunk / SSE 和普通持久化。
- planner 的自由文本 route / refusal reason 不再进入 SSE step、search/message metadata、span 或 debug log，只保留枚举、布尔值、数量与稳定 reason code。
- synthetic marker 覆盖 query、history、ordinary output、provider exception echo、planner reason、`<think>` reasoning 和 unsafe raw output；负向断言检查真实 worker recorder 参数、Redis chunk 转换后的 SSE frame、message / metadata 更新对象、结构化日志和 span 事件。
- 聚焦命令覆盖 19 个 config / observability / provider / service / worker / workflow 测试文件，结果为 `232 passed`（仅有已知 FastAPI / Starlette deprecation warning）。该次未记录文件清单，且 WS8 之后又改动过 planner 相关测试，因此 `232` 已不可复现：当前变更集内任意 19 个 unit 测试文件的用例数上限是 `227`。可复现的等价口径改为「本工作项涉及的全部 unit 测试文件」，共 25 个文件，2026-07-26 复核为 `242 passed`。该 checkpoint 真实关闭 WS6 与 WS7，但不代表 WS5 的 AWS 送达或 WS8 的最终门禁已完成。

### WS8 local matrix — 本地验收完成，AWS receiver 证据待补（2026-07-17）

- `bash -n deploy/monitoring/cloudwatch-setup.sh deploy/monitoring/cloudwatch-verify-delivery.sh` 通过；审计时发现验证脚本错误依赖系统级 `python`，现已改为项目约定的 `uv run python`，对应静态回归 `3 passed`。本机未安装 ShellCheck，因此没有伪记 ShellCheck 结果。
- 使用当前已认证 AWS CLI 调用只读 `aws logs test-metric-filter`，逐一验证 API 5xx、API latency、queue depth、oldest pending、heartbeat、terminal failure、Redis risk、probe failure 和 synthetic delivery 共 9 个 filter pattern；全部被 CloudWatch 接受且各自命中预期 JSON 样本。该检查没有创建或修改 AWS 资源。
- 全量后端行为门：`make qa-test-unit PYTEST_ARGS='-q'` 为 `1049 passed, 9 skipped`；`make qa-test-component PYTEST_ARGS='-q'` 为 `42 passed`。第一次全量 unit 暴露 3 个仍期待 planner 自由文本 reason 的旧断言；更新为稳定码并加入原始 reason 不出现的负向断言后，相关文件 `11 passed`，随后全量通过。
- 静态与仓库门：`qa-lint`、`qa-boundaries`、`qa-test-markers`、`qa-typecheck`、`qa-layer-deps`、`qa-alembic-check`、`qa-config-check`、`qa-skill-check` 和 `qa-docs` 通过；本次变更的 46 个已跟踪修改 Python 文件与 9 个新增未跟踪 Python 文件（合计 55 个）通过 `ruff format --check`，`git diff --check` 通过。`qa-typecheck` 仅报告仓库既有 warning，退出码为 0。
- Monorepo 默认前端链作为交叉回归通过：lint、typecheck、`38` 个 Vitest 文件中的 `316 passed`、production build 和 bundle budget check 均成功；bundle gzip `461.9 KiB`，低于 `504.0 KiB` 限制。
- 全局 `qa-format-check` 仍被 7 个本工作项未修改的既有 unit-test 文件拦截；`qa-no-while-true` 仍只命中未修改的 `scripts/qa/check_serena_mcp.py:52`。这些基线问题没有被本工作项顺手改写，也不掩盖在 checkpoint 证据中。
- AWS CLI 和当前凭据可用，但 `deploy/.env.ec2` 缺失，因而无法安全确定目标 region、log group、SNS topic 与 receiver。尚未应用 CloudWatch 资源、尚未发出 controlled marker，也没有 receiver 收件证明；WS5 保持 `in_progress`，WS8 因依赖 WS5 保持 `pending`，checkpoint 只能是 `implemented` 而不是 `validated`。

## 暂缓 / 不纳入范围

- 真实 SMS provider、真实号码 smoke、短信配额 / 到达率告警、短信服务恢复。
- RDS snapshot / PITR、S3 version / object restore、Redis / Worker 生产中断恢复、EC2 / Tunnel / secret 重建和 RPO / RTO 实测。
- 自动跨 AZ 接管、完整 chaos suite、自动化灾备编排、通用 DLQ 或替换 RabbitMQ / Redis Streams。
- 全量 SLO / dashboard 平台、自托管 Alertmanager、IaC 重构、所有日志 producer 的统一 telemetry sanitizer。
- Langfuse 原文采集的生产 opt-in 流程、完整脱敏 / sampling / access / retention 治理。
- CSP enforcement、逐句 LLM safety judge、完整 badcase 加密平台和高级流式分类器。

## Open Decisions 说明

当前没有阻塞启动的 open decision，默认采用以下取舍：复用现有 AWS CLI / CloudWatch / SNS 路径，不在本轮引入 IaC；queue oldest 使用 PostgreSQL durable facts，不解析 TaskIQ 私有消息；生产环境不提供内容采集 opt-in；受控告警验证只使用非恢复型 synthetic signal。若这些取舍发生变化，应先更新 `manifest.yaml` 的 open decisions，再扩大实现范围。
