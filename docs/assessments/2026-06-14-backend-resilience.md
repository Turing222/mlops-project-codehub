# 后端熔断与降级设计评估报告

> 日期：2026-06-14
> 范围：`backend/` 后端服务的熔断（circuit breaking）、降级（graceful degradation）及其配套韧性机制（限流、并发、超时、重试）
> 性质：只读静态分析，结论均给出 `文件:行号` 证据
> 证据基线：评估时的 `backend/` 实现、静态检索结果与文中测试证据
> 状态：冻结；后续修复记录仅用于解释历史结论，现状以代码和长期文档为准

## 1. 概述与结论速览

后端整体采用「**单点熔断 + 多层降级 + 边界限流/并发/超时**」的韧性策略，核心面向 AI 主链路（LLM、RAG、Rerank、外部检索）。

- **熔断**：仅有一处真正的断路器实现 `CircuitBreaker`，且只挂在 LLM 调用上，属进程内状态、不跨 worker 协调。
- **降级**：覆盖面较广，至少 7 处「失败即退回可用结果」的降级路径，是本项目韧性设计的主体。
- **配套**：Redis 滑动窗口限流（HTTP 入口）、进程内 semaphore 并发闸（LLM/DB）、多级超时（流式/Rerank/Planner/外部检索）、provider 路由 fallback。

总体评价：**降级设计成熟、覆盖完整；熔断设计偏单薄，存在半开探测放量、流式成功标记过早等可改进点**。详见第 6、7 节。

---

## 2. 机制清单与统计

| 类别 | 实现位置 | 数量 | 状态作用域 |
| --- | --- | --- | --- |
| 熔断 CircuitBreaker | `backend/core/circuit_breaker.py` | 1 个实现 / 1 处接入（LLM） | 进程内 |
| 降级 fallback | RAG / Rerank / Planner / 外部检索 / FeatureFlag / 路由 | ≥7 处 | 调用内 |
| 限流 RateLimiter | `backend/middleware/rate_limit.py` | 1 个实现 / ~9 组配额 | Redis 分布式 |
| 并发闸 Semaphore | `backend/core/concurrency.py` | 2 个（LLM=5 / DB=10） | 进程内 |
| 超时 Timeout | chat stream / rerank / planner / 外部检索 / PG | ≥6 处 | 调用内 |
| 重试 Retry | LLM provider `max_retries`（路由模式下置 0） | provider 级 | 调用内 |

> 关键观察：熔断只有 1 处，降级有 7+ 处——本系统的韧性重心明显落在「降级」而非「熔断」。

---

## 3. 熔断设计详评

### 3.1 实现概览

`backend/core/circuit_breaker.py` 是标准三态断路器：

- 状态机 `CLOSED → OPEN → HALF_OPEN`（`circuit_breaker.py:17-21`）。
- `acquire()` 在 OPEN 且未到冷却期时直接抛 `CIRCUIT_BREAKER_OPEN` 业务异常快速失败（`:57-64`）；冷却到期转 HALF_OPEN 放行探测（`:46-56`）。
- `on_success()` 复位为 CLOSED、清零计数（`:68-81`）；`on_failure()` 累加失败，半开探测失败立即重新 OPEN，关闭态达阈值则 OPEN（`:83-113`）。
- 用 `asyncio.Lock` 保证状态切换原子性，时间基于 `time.monotonic()`，避免系统时钟漂移。
- 全程结构化日志（`event=circuit_breaker_*` + `service` + `circuit_state`），可观测性良好。

### 3.2 接入点与生命周期

- 唯一接入点：`backend/ai/providers/llm/pydantic_ai_service.py`，流式 `:127/137/155` 与非流式 `:193/200/221` 各包一对 acquire/on_success/on_failure。
- 阈值/冷却来自配置：`LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5`、`LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS=30`（`backend/config/ai_settings.py:102-103`）。
- **状态作用域正确**：断路器实例随 LLM service 缓存于 worker 容器单例（`backend/worker/dependencies.py:62-64` + `:214-222` 的 `_container` 进程单例），故失败计数能在同一 worker 进程内跨任务累积——这是断路器有效的前提，设计无误。
- LLM 真实调用发生在 worker 侧（web 经 `AbstractTaskDispatcher` 派发到 worker），断路器恰好落在执行端，位置合理。

### 3.3 熔断设计的问题

1. **半开态放量（最值得修）**：`acquire()` 在 HALF_OPEN 时对所有并发请求一律放行（`circuit_breaker.py:65-66`），未限制探测并发。OPEN→HALF_OPEN 瞬间，积压的并发请求会同时涌向尚在恢复的下游。标准做法应只放 1 个（或少量）探测请求。
   - **缓解项（降低严重级的依据）**：LLM 调用外层套有 `llm_concurrency_slot`，实际 LLM 请求在 `worker_generation_workflow.py:557-565 / 783-792` 中被 semaphore 包裹，故半开探测的并发被压到单 worker ≤ `LLM_MAX_CONCURRENCY=5`，并非无上限涌入。仍是理想「单探测」的约 5 倍，但不会瞬间数百路涌入。综合判定为**中**级（详见 6.2）。
   - 验证状态：**静态推断**（读码确认放行逻辑与 semaphore 包裹关系），未做并发复现实验。
2. **流式「成功」标记过早**：`stream_response` 在 `agent.run_stream(...)` 刚建立连接、尚未产出 token 时即调用 `on_success()`（`pydantic_ai_service.py:137`）。若流在 `async for delta` 中途失败，会先被记为成功（计数清零）再记失败（计数=1），削弱熔断灵敏度；连接建立成功但流式即坏的 provider 几乎无法触发熔断。
   - 验证状态：**静态推断**（读码确认 `on_success` 位于流迭代之前、`on_failure` 在 except 中），未编写中途失败用例复现计数清零行为。
3. **覆盖面窄**：熔断只保护 LLM。Rerank、外部检索（Tavily）、GrowthBook、数据库等外部依赖均无断路器，仅靠降级/超时兜底，无法在持续故障时「快速失败避免雪崩」。
4. **进程内、不跨 worker**（实现注释已自述，`circuit_breaker.py:4`）：多 worker/多容器各自计数，集群层面阈值被放大 N 倍，OPEN 触发偏晚。属已知权衡，非缺陷，但需在容量评估时知悉。

---

## 4. 降级设计详评

降级是本系统韧性的主体，遵循统一原则：**非业务异常退回「可用的次优结果」，保证主链路（聊天）不中断**。逐项如下：

### 4.1 LLM 路由 fallback

`backend/ai/providers/llm/routing_service.py` 按候选顺序逐个尝试，失败切换下一个，全败才抛 `LLM_ROUTING_FAILED`（含各候选尝试摘要，`:79-83/108-112`）。

- 候选来自多 profile / 多 API key 展开（`backend/ai/providers/llm/factory.py:26-52`）。
- **流式安全边界处理到位**：一旦已发出 chunk 就不再切换候选（`routing_service.py:60-68`），避免向用户重复/错乱输出——这是流式 fallback 的正确做法。
- 路由模式下把单 provider 的 `max_retries` 置 0（`factory.py:40`），把重试责任上移到路由层，避免「重试 × 候选」的延迟叠加。

### 4.2 RAG 检索降级（多处）

`backend/services/rag_service.py` 注释明示「非业务异常降级为空检索上下文」（`:5`），实测覆盖各检索模式：

- 向量检索失败 → 无检索上下文（`:101`）
- 全文检索失败 → 无检索上下文（`:236`）
- 混合检索失败 → 无检索上下文（`:272`）
- rerank 候选检索失败 → 退回普通检索（`:172`）
- 上层 `chat_context_builder.py:417`：RAG 整体失败 → 降级为普通对话。

### 4.3 Rerank 降级

- Native rerank 失败 → 退回候选原始排序 `select_rerank_fallback_candidates`（`rag_service.py:133-135 / 202-203`）。
- Rerank provider 自带超时 `RAG_RERANK_TIMEOUT_SECONDS=15`（`ai_settings.py:124`，应用于 `dashscope_rerank.py:97` / `bifrost_rerank.py:110`），超时由调用方降级（`bifrost_rerank.py:5` 注释自述）。

### 4.4 RAG Planner 降级

`backend/services/rag_planning_service.py`：planner LLM 失败或超时 → 返回 `from_settings` 的默认执行计划（`:241/284-291`），原因标记 `RAG_PLANNER_FALLBACK_REASON`（`:36`）；低置信度时降级模型档位（`:185`）。超时 `RAG_PLANNER_TIMEOUT_SECONDS=8` 经 `asyncio.wait_for` 强制（`:265-274`）。

### 4.5 外部检索（Tavily）降级

`backend/services/external_context_service.py`：任意异常 → `降级为空结果`（`:112`），带 `EXTERNAL_CONTEXT_TIMEOUT_SECONDS=6` 的 httpx 超时（`ai_settings.py:143` + `:96`）。属「锦上添花型」上下文，降级为空对主链路无损，合理。

### 4.6 Feature Flag 降级

`backend/services/feature_flag_service.py`：GrowthBook CDN 拉取带 3s 超时（`:73`），失败时**保留本地缓存**（`:84`）；云端未定义的 flag 回落**代码内默认值**（`_eval_flag` / `_AI_SYSTEM_FLAG_DEFAULTS`，`:138-141`）。双层降级（缓存→代码默认），开关系统不会因 CDN 故障而失效。

### 4.7 SMS Mock 降级

`backend/services/sms_service.py:113-114`：mock 模式下验证码仅写服务端日志，属环境降级而非故障降级，用于无短信通道的环境。

---

## 5. 配套韧性机制

### 5.1 限流（分布式，质量较高）

`backend/middleware/rate_limit.py` 用 **Redis sorted set 滑动窗口 + Lua 原子脚本**实现（`:26-50`），在 Redis 端原子完成「清窗→计数→写入」，杜绝并发穿透；超限抛 `app_too_many_requests`（`:113`）。可信代理网段才读代理头，防 IP 伪造（`:5/121-126`）。配额按接口分级（`backend/config/web_settings.py:100-135`）：SMS、注册、登录、聊天、遥测、CSP 各有独立 times/seconds，约 9 组。这是全套机制中分布式协调最完善的一处。

### 5.2 并发闸（进程内）

`backend/core/concurrency.py`：LLM 与 DB 各一个 `asyncio.Semaphore`（`LLM_MAX_CONCURRENCY=5` / `DB_MAX_CONCURRENCY=10`，`worker_settings.py:19-22`），经 `traced_semaphore_slot` 记录排队/持有时长到 trace span（`:46-77`）。注释自述非分布式限流、多 worker 各自额度（`:5`）。在 chat workflow、session orchestrator、worker generation 等处套用，对下游形成背压。

### 5.3 多级超时

| 超时项 | 默认值 | 配置位置 | 强制方式 |
| --- | --- | --- | --- |
| 首条消息 | 30s | `CHAT_STREAM_FIRST_MESSAGE_TIMEOUT_SECONDS` | `web_stream_workflow.py:214-227` |
| 消息间隔 | 10s | `CHAT_STREAM_MESSAGE_TIMEOUT_SECONDS` | `:262-272` |
| Rerank | 15s | `RAG_RERANK_TIMEOUT_SECONDS` | httpx timeout |
| Planner | 8s | `RAG_PLANNER_TIMEOUT_SECONDS` | `asyncio.wait_for` |
| 外部检索 | 6s | `EXTERNAL_CONTEXT_TIMEOUT_SECONDS` | httpx timeout |
| PG 连接 | 10s | `POSTGRES_CONNECT_TIMEOUT_SECONDS` | 连接参数 |

聊天流式超时区分「首 token 等待」与「token 间隔」两类，超时映射为 `LLM_TIMEOUT` / `LLM_STREAM_MESSAGE_TIMEOUT` 业务码，颗粒度细，体验友好。

### 5.4 重试与后台恢复

- LLM provider 级 `max_retries`（`pydantic_ai_service.py:58/256`），路由模式下置 0 交由路由层兜底。
- 后台恢复任务：`recover_stale_knowledge_ingestions`（每 15 分钟）扫描卡死的知识入库并恢复（`backend/worker/tasks/knowledge_tasks.py:71-90`），属「自愈型」韧性补充。
- 未引入 tenacity 等通用退避库，重试策略分散在各 provider/路由，无统一指数退避。

---

## 6. 评估结论

### 6.1 优点

1. **降级体系完整且原则统一**：7+ 处降级一致遵循「非业务异常 → 退回可用次优结果 → 主链路不中断」，且严格区分「业务异常（向上抛）」与「技术异常（降级）」（如 `pydantic_ai_service.py:152-153` 先 `except AppException: raise`）。这是整套设计最成熟的部分。
2. **熔断核心实现规范**：三态机正确、锁保护原子、`monotonic` 计时、结构化日志齐全；状态作用域定位准确（worker 进程单例）。
3. **限流工程质量高**：Redis + Lua 滑动窗口是分布式限流的正确实现，按接口分级配额。
4. **超时分层细致**：首 token / token 间隔分离，各外部依赖独立超时并映射到明确业务码。
5. **流式 fallback 边界严谨**：已发 chunk 不切候选、不中途熔断误判（路由层），符合流式语义。
6. **可观测性贯穿**：熔断、限流、并发、超时均写 trace span / 结构化日志，便于线上定位。

### 6.1.1 现有测试覆盖

- 已有：`tests/unit/ai/test_pydantic_ai_llm_service.py` 覆盖「失败标记熔断」（`:170 test_generate_response_marks_circuit_failure`）与「熔断阈值/冷却可注入」（`:204 test_circuit_breaker_config_can_be_injected`）。
- **覆盖缺口**：
  - `test_generate_response_marks_circuit_failure` 使用 `FakeCircuit` 桩件（`:174`），验证的是 **service 与断路器的接线**，而非 `CircuitBreaker` 状态机本身。
  - `backend/core/circuit_breaker.py` **无专属单测**（`rg -l circuit_breaker tests/` 仅命中上述 service 测试）。CLOSED→OPEN 阈值触发、OPEN→HALF_OPEN 冷却转换、半开探测失败重开、半开放量等状态机路径**均未被直接测试**。
  - 6.2 列出的两条「中」级缺陷（半开放量、流式 `on_success` 时机）正落在未覆盖路径上——这也是它们只能标「静态推断」的原因。
- 建议：补 `tests/unit/core/test_circuit_breaker.py`，对状态机全路径 + 半开并发探测做用例，作为后续修复（6.3 建议 1/2）的回归基线。

### 6.2 风险与缺陷（按优先级）

| 级别 | 问题 | 位置 | 影响 | 验证状态 |
| --- | --- | --- | --- | --- |
| 中 | 半开态不限并发探测，恢复瞬间放量（受 LLM semaphore=5 上限缓解） | `circuit_breaker.py:65-66` | 单 worker 最多 5 路探测涌向恢复中的下游 | 静态推断，建议补并发用例复现 |
| 中 | 流式 `on_success` 标记过早，中途失败先被记成功 | `pydantic_ai_service.py:137` | 削弱熔断灵敏度 | 静态推断，建议补中途失败单测 |
| 中 | 熔断仅覆盖 LLM，rerank/外部/DB/GrowthBook 无断路器 | 全局 | 持续故障下无快速失败保护 | 已确认（rg 全量检索仅 LLM 接入）|
| 低 | 熔断进程内、不跨 worker，集群阈值被放大 | `circuit_breaker.py:4` | OPEN 触发偏晚（已知权衡） | 已确认（实现注释自述）|
| 低 | 无统一退避策略，重试分散 | 各 provider | 抖动场景退避不一致 | 已确认 |

> 说明：「静态推断」指仅经读码分析、未实际运行复现；「已确认」指有检索/注释/代码直接佐证。建议落地修复前，先对两条「中」级静态推断项补单测复现，避免误判。

### 6.3 改进建议

1. **半开限流探测**：在 `CircuitBreaker` 加半开探测名额（如单 `asyncio.Semaphore(1)` 或 `half_open_max_calls`），HALF_OPEN 仅放行限定并发，其余仍快速失败。——优先级最高，改动小。
2. **修正流式成功时机**：把 `on_success()` 从「流建立后」移到「流正常迭代结束后」（`stream_response` 的 `async for` 完成、`set_span_attributes` 之前），使中途失败能正确计入熔断。
3. **扩大熔断覆盖**：将断路器复用到 rerank、Tavily 外部检索、GrowthBook 等高频外部调用上（与现有降级叠加：熔断快速失败 + 降级兜底）。
4. **可选跨进程协调**：若集群规模增长，考虑把失败计数下沉到 Redis（与限流共用基础设施），实现集群级熔断；否则在容量评估时按 worker 数放大阈值预期。
5. **统一退避**：引入 tenacity 或自研指数退避 + 抖动，收敛分散的重试逻辑。

---

## 7. 附：核心文件索引

- 熔断：`backend/core/circuit_breaker.py`、`backend/ai/providers/llm/pydantic_ai_service.py`
- 路由 fallback：`backend/ai/providers/llm/routing_service.py`、`backend/ai/providers/llm/factory.py`
- 降级：`backend/services/rag_service.py`、`rag_planning_service.py`、`external_context_service.py`、`feature_flag_service.py`、`backend/ai/core/chat_context_builder.py`
- 限流：`backend/middleware/rate_limit.py`
- 并发：`backend/core/concurrency.py`
- 超时：`backend/application/chat/web_stream_workflow.py`、`backend/config/ai_settings.py`
- 配置：`backend/config/ai_settings.py`、`web_settings.py`、`worker_settings.py`、`settings.py`

---

## 8. 修复记录（2026-06-14 后续落地）

> 本节记录评估结论（§6.2 / §6.3）在代码中的落实情况；正文 §1–§7 保留为**修复前**只读快照，便于对照。

### 8.1 已落实项

| 评估建议 | 落实 | 测试证据 |
| --- | --- | --- |
| §6.3.1 半开限流探测 | `CircuitBreaker.half_open_max_calls`（默认 1）；过期探测 `on_success` 在 OPEN 态忽略 | `tests/unit/core/test_circuit_breaker.py` |
| §6.3.2 流式 `on_success` 时机 | 移到 `async for` 迭代结束后 | `test_stream_midfailure_marks_circuit_failure_not_success` |
| §6.3.3 扩大熔断覆盖 | Rerank（bifrost/dashscope）、Tavily、GrowthBook | 各 provider/service 单测 + `test_retrieve_with_rerank_degrades_when_circuit_breaker_open` |
| §6.1.1 状态机单测缺口 | 新增 `tests/unit/core/test_circuit_breaker.py` | 11 用例（含并发半开探测） |

### 8.2 接入点（修复后）

| 服务名 | 实现位置 | 熔断打开时行为 |
| --- | --- | --- |
| `llm:*` | `pydantic_ai_service.py` | 向上抛 `CIRCUIT_BREAKER_OPEN`（路由层 fallback） |
| `rerank:bifrost` / `rerank:dashscope` | `bifrost_rerank.py` / `dashscope_rerank.py` | `rag_service` 降级为候选原始排序 |
| `external_context:tavily` | `external_context_service.py` | 降级为空结果 |
| `growthbook` | `feature_flag_service.py` | 沿用本地缓存 / 代码默认 |

配置项：`LLM_CIRCUIT_*`、`RAG_RERANK_CIRCUIT_*`、`EXTERNAL_CONTEXT_CIRCUIT_*`（`ai_settings.py`）、`GROWTHBOOK_CIRCUIT_*`（`settings.py`）。

### 8.3 仍未纳入本次范围

- §6.3.4 Redis 集群级熔断（可选）
- §6.3.5 统一退避（可选）
- DB / Embedding 熔断（见 `docs/platform/api-keys-and-degradation.md` §7 #2）
- 进程内不跨 worker（已知权衡，未改）
