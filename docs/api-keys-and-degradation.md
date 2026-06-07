# API Key 需求与故障降级行为

本文档梳理 Dewflow 后端各 **API Key / Secret** 对应的功能、最小需求分层，以及 **缺失或上游服务故障时的告警与降级行为**。

- 关注 **怎么部署**（`make` 命令、部署顺序、secret 准备）请看 [deploy-ec2.md](deploy-ec2.md)。
- 本文档关注 **哪个 key 启用哪个功能、缺了/挂了会怎样**，与具体环境（EC2 / k8s / local-prod）无关。

> 所有结论均来自代码与配置直读，关键处附 `文件:行号`。配置如有变动，请同步更新本文。

---

## 1. 配置优先级与一个常见坑

### 1.1 优先级

Secret/配置的解析优先级（高 → 低，见 [ai_settings.py:181-187](../backend/config/ai_settings.py#L181-L187)）：

```
环境变量(env)  >  .env / dotenv  >  *_FILE secret 文件  >  YAML(configs/app/base.yaml + {APP_ENV}.yaml)
```

含义：`deploy/.env.ec2` 里的值会 **覆盖** `configs/app/*.yaml`。EC2 部署时 `APP_ENV=prod`，所以生效配置 = `base.yaml` ∪ `prod.yaml`，再被 `.env.ec2` 覆盖。

Secret 注入机制：`FOO_FILE` 指向的文件内容会在进程导入时被读入环境变量 `FOO`（白名单见 [secret_env.py:16-41](../backend/core/secret_env.py#L16-L41)）。文件缺失只记一条 warning，不中断启动（[secret_env.py:53-55](../backend/core/secret_env.py#L53-L55)）。

### 1.2 坑：`RAG_*_ENABLED` 是无效配置

如果你在旧模板或历史部署记录里看到 `RAG_PLANNER_ENABLED` / `RAG_RERANK_ENABLED`，它们 **不是真实配置字段**（`AISettings` 没有这两个字段，`extra="ignore"` 直接丢弃）。它们 **不控制任何行为**。真正的控制面是：

| 功能 | 真正的开关 |
|---|---|
| LLM | `LLM_PROVIDER` + 启动校验 [validate_llm_configs](../backend/config/llm.py#L236-L264) |
| RAG planner | GrowthBook flag `enable-rag-planner`（默认 False） |
| RAG rerank（web 路径） | GrowthBook flag `enable-rag-rerank`（默认 False），见 [api/deps/ai.py:33-34](../backend/api/deps/ai.py#L33-L34) |
| RAG rerank（worker 路径） | planner/flag 决定是否尝试 rerank；`RAG_RERANK_PROVIDER` 只决定 worker 能否构造 rerank 实现，构造或运行失败都会降级，见 [rag_planning_service.py:142-145](../backend/services/rag_planning_service.py#L142-L145) 与 [worker/dependencies.py:100-129](../backend/worker/dependencies.py#L100-L129) |
| 联网检索（Tavily） | flag `enable-external-context` + `TAVILY_API_KEY` 非空 |

### 1.3 EC2 默认态（模板 + APP_ENV=prod）的生效值

| 配置 | 生效值 | 来源 |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `.env.ec2` 覆盖 |
| `RAG_EMBED_PROVIDER` | `mock` | `.env.ec2` + [base.yaml:29](../configs/app/base.yaml#L29) |
| `RAG_RERANK_PROVIDER` | `dashscope` | [base.yaml:31](../configs/app/base.yaml#L31)（`.env.ec2` 未覆盖） |
| `RAG_PLANNER_PROVIDER` | `bifrost_flash` | [base.yaml:36](../configs/app/base.yaml#L36)（`.env.ec2` 未覆盖） |
| GrowthBook flags | 全部走 **代码默认**（基本 False） | `GROWTHBOOK_SDK_KEY` 为 dummy → 不拉 CDN |

> 注意 embedding 生效值是 **mock 而非 dashscope**（虽然 [ai_settings.py:148](../backend/config/ai_settings.py#L148) 的代码默认是 dashscope，但被 base.yaml/env 覆盖为 mock）。真正会调 DashScope 的是 **rerank**。
>
> 在 EC2 上一键复核生效值：
> ```bash
> APP_ENV=prod LLM_PROVIDER=mock RAG_EMBED_PROVIDER=mock \
>   uv run python -c "from backend.config.ai_settings import get_ai_settings as g; s=g(); \
>   print('rerank=',repr(s.RAG_RERANK_PROVIDER),'planner=',repr(s.RAG_PLANNER_PROVIDER))"
> ```

---

## 2. Key 分层（最小需求）

Secret 文件位于 [secrets/ec2/](../secrets/ec2)（EC2）或 [secrets/local-prod/](../secrets/local-prod)（本地演练）。`make deploy-ec2-secrets-prepare` 会为 Tier 0 生成随机值、为其余创建空文件。

### Tier 0 — 服务间凭证（启动必需，已自动生成）

| Key | 文件 | 用途 | 缺失后果 |
|---|---|---|---|
| `SECRET_KEY` | `secret_key.txt` | JWT/会话签名 | 启动校验失败 [web_settings.py:133-138](../backend/config/web_settings.py#L133-L138) |
| `POSTGRES_PASSWORD` | `postgres_password.txt` | DB 密码 | DB 连接/迁移失败 |
| `REDIS_PASSWORD` | `redis_password.txt` | Redis 密码 | Redis 起不来 |

### Tier 1 — 让产品"真正可用"的最小集

| 能力 | 需要的 Key | 配置动作 |
|---|---|---|
| 真实对话（脱离 mock） | `DEEPSEEK_API_KEY`（直连）**或** `BIFROST_API_KEY` + `BIFROST_ENCRYPTION_KEY`（网关） | `LLM_PROVIDER=deepseek` / `resilient` / `bifrost_pro` |
| 故障转移（可选但推荐） | 路由内 **每个** profile 的 key，如 `resilient` 需 `DEEPSEEK_API_KEY` + `GEMINI_API_KEY` | `LLM_PROVIDER=resilient`（启动校验要求全齐） |
| 知识库 RAG 有意义的向量 | 切到真实 embedding：`DASHSCOPE_API_KEY`（qwen3）或 `GEMINI_API_KEY`/`GOOGLE_API_KEY`（google） | `RAG_EMBED_PROVIDER=dashscope`/`google`，**切换后需重建已入库向量** |
| 生产存储 | `S3_BUCKET` 必填；凭证优先用 **EC2 instance role**（AK/SK 留空） | `STORAGE_BACKEND=s3` |

### Tier 2 — 可选增强（缺失基本无害，详见第 4 节降级行为）

`GROWTHBOOK_SDK_KEY`、`TAVILY_API_KEY`、`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`、`GITHUB_TOKEN`、Google 登录（`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`GOOGLE_ALLOWED_REDIRECT_URIS`）、各 `*_API_KEY_2`、`COHERE_API_KEY`（仅 Bifrost 上游用）。

> **smoke 与 ec2 是两份 secret**：smoke 测试读 `secrets/smoke/`，EC2 部署读 [secrets/ec2/](../secrets/ec2)。在 smoke 里填了 key **不等于** EC2 也有。要用的 key 必须确认 `secrets/ec2/` 对应文件非空（见第 5 节坑）。

---

## 3. Key → 功能 → 缺失行为

| Key | 功能 | 缺失时行为 |
|---|---|---|
| `DEEPSEEK_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` / `OPENAI_API_KEY` | LLM 直连 provider（Gemini/Google 同时用于 google embedding） | `LLM_PROVIDER` 指向它而 key 空 → **启动 ValueError**（[llm.py:236-264](../backend/config/llm.py#L236-L264)）；非该 provider 则无需 |
| `BIFROST_API_KEY` + `BIFROST_ENCRYPTION_KEY` | Bifrost 网关自身 | 用 `bifrost*` provider 且缺失 → 启动/网关失败 |
| `DASHSCOPE_API_KEY` | qwen3 embedding / dashscope rerank / Bifrost 上游 | 见第 4 节（构造期 vs 运行期，行为不同） |
| `RAG_EMBED_API_KEY` | embedding 通用 key（优先于 provider 专用 key） | 同上 |
| `S3_BUCKET` | S3 存储桶 | `STORAGE_BACKEND=s3` 时构造对象存储即 ValueError（[object_storage.py:354-355](../backend/services/object_storage.py#L354-L355)） |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | S3 静态凭证 | **留空更好**：代码按真值判断（[object_storage.py:336-341](../backend/services/object_storage.py#L336-L341)），空 → boto3 走默认链/实例角色 |
| `GROWTHBOOK_SDK_KEY` | 功能开关总闸 | dummy/缺失 → 不拉 CDN，所有 flag 走代码默认（[feature_flag_service.py:18-26](../backend/services/feature_flag_service.py#L18-L26)），无告警 |
| `TAVILY_API_KEY` | 联网检索 | **静默跳过**，无 warning（[external_context_service.py:161-165](../backend/services/external_context_service.py#L161-L165)） |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | LLM 调用链路追踪 | **静默 no-op + 一条启动 warning**（[langfuse_utils.py:156-162](../backend/observability/langfuse_utils.py#L156-L162)），零功能影响 |
| `GITHUB_TOKEN` | repo 分析鉴权（提额/私有库） | 降级为**匿名调用**（[github.py:80](../backend/application/repo_analysis/github.py#L80)），不崩 |
| `GOOGLE_CLIENT_SECRET`(+ID+redirect) | Google 登录 | `GOOGLE_OAUTH_ENABLED=false`（默认）→ 功能关闭，无需 key；启用而缺失 → **启动 ValueError**（[web_settings.py:185-197](../backend/config/web_settings.py#L185-L197)） |
| `*_API_KEY_2` / `COHERE_API_KEY` | 同 provider 第二把轮询 key / Cohere（Bifrost 上游） | 不用对应 provider 即无需 |

> `GOOGLE_CLIENT_SECRET`（OAuth 登录）与 `GOOGLE_API_KEY`（Gemini embedding/LLM）是 **两个独立用途**，分属 `WebSettings` 和 `AISettings`。

---

## 4. 运行期故障降级矩阵（核心）

**关键区分 —— 构造期 vs 运行期**

| 阶段 | 触发条件 | 是否降级 |
|---|---|---|
| **构造期**（建 client 对象） | 只检查 **key 是否为空字符串** | ❌ key 空 → `ValueError`，**不被捕获** → 任务/启动崩 |
| **运行期**（真正调上游） | 服务挂 / 超时 / 429 / key 失效 | ✅ 一律捕获 + warning + 降级 |

构造期 **不校验 key 有效性**，只看非空（[rerank/factory.py:58-61](../backend/ai/providers/rerank/factory.py#L58-L61)、[:74-77](../backend/ai/providers/rerank/factory.py#L74-L77)）。所以 key 非空（哪怕是错的）→ 构造成功，错误推迟到运行期 → 走降级。

### 降级矩阵

| 组件 | 失败场景 | 行为 | 证据 |
|---|---|---|---|
| LLM（mock） | — | 返回固定假回复，无需 key | [mock_provider.py](../backend/ai/providers/llm/mock_provider.py) |
| **LLM（单 provider）** | 真实 provider 挂 | ❌ **无 fallback**：熔断器开 → 对话报错给用户 | [circuit_breaker.py](../backend/core/circuit_breaker.py) |
| LLM（`resilient` 路由） | 首选挂 | ✅ 故障转移到下一 profile（deepseek→gemini）；流式仅在首 chunk 前可切 | [routing_service.py:52-112](../backend/ai/providers/llm/routing_service.py#L52-L112) |
| RAG 检索（query embedding） | embedding 调用失败 | ✅ orchestrator 兜底捕获 → 退回**普通对话**（无 KB 上下文） | [worker_rag_orchestrator.py:388-392](../backend/application/chat/worker_rag_orchestrator.py#L388-L392) |
| RAG rerank（运行期调用） | DashScope 挂/超时/429/key 失效 | ✅ 退回候选原始顺序（不 rerank） | [rag_service.py:137-138](../backend/services/rag_service.py#L137-L138)、[:227-229](../backend/services/rag_service.py#L227-L229)、[orchestrator:471-479](../backend/application/chat/worker_rag_orchestrator.py#L471-L479) |
| **RAG rerank（构造期）** | `RAG_RERANK_PROVIDER` 非空但 key **为空/无效** | ✅ **已修复（#4）**：worker `get_rerank_service` 加 try/except → warning（`event=worker_rerank_init_degraded`）+ 退回无 rerank，不再崩任务 | [worker/dependencies.py:95-123](../backend/worker/dependencies.py#L95-L123) |
| RAG planner | 规划失败/超时 | ✅ 退回默认计划 | [worker_rag_orchestrator.py:313-315](../backend/application/chat/worker_rag_orchestrator.py#L313-L315) |
| 联网检索（Tavily） | key 缺失 / 运行期失败 | ✅ 静默跳过 / 退回空，仅用 KB | [orchestrator:370-372](../backend/application/chat/worker_rag_orchestrator.py#L370-L372) |
| **知识入库（doc embedding）** | embedding 调用失败 | ⚠️ 文件标记 `FAILED` + 清理半成品，**但无自动重试**，需手动重传 | [ingestion_workflow.py:154-179](../backend/application/knowledge/ingestion_workflow.py#L154-L179)、[knowledge_tasks.py:168](../backend/worker/tasks/knowledge_tasks.py#L168) |
| Langfuse | key 缺失 / 初始化失败 | ✅ 静默 no-op + warning | [langfuse_utils.py:156-162](../backend/observability/langfuse_utils.py#L156-L162) |
| GitHub repo 分析 | token 缺失 | ✅ 降级匿名调用 | [github.py:80](../backend/application/repo_analysis/github.py#L80) |
| GrowthBook | key dummy/缺失 / CDN 失败 | ✅ 退回代码默认 flag | [feature_flag_service.py:66-85](../backend/services/feature_flag_service.py#L66-L85) |
| S3 存储 | bucket 缺失 | ❌ 构造存储时 ValueError | [object_storage.py:354-355](../backend/services/object_storage.py#L354-L355) |
| S3 存储 | 凭证不可解析 | ⚠️ 构造不报错，首次 S3 操作时 boto3 报错 | [object_storage.py:328-347](../backend/services/object_storage.py#L328-L347) |

**结论**：对话链路（retrieval / rerank / planner / 联网）**运行期故障几乎全部优雅降级**，对话总能完成（质量下降而已）。曾经的硬失败"① rerank 构造期空 key"已在 **#4 修复**（改为降级）。当前剩余硬失败点只有两类：② 单 LLM provider 无 fallback（已评估，采用**方案 A** 接受为已知风险，见第 7 节）；③ 知识入库无自动重试（改进方案见第 7 节 #2）。

---

## 5. 韧性矩阵：熔断 / 重试 / 超时 / 降级

第 4 节是"按失败场景看降级"，本节是"按调用点看它拥有哪些韧性手段"（读代码直得）：

| 调用点 | 熔断 | 重试 | 超时 | 失败降级 |
|---|---|---|---|---|
| **LLM** `PydanticAILLMService` | ✅ `CircuitBreaker`（进程内，5 次/30s） | ✅ OpenAI SDK `max_retries`（单 profile=默认 2；路由内=0） | ✅ chat 首包 30s / 续包 10s | ✅ 路由跨 profile fallback |
| **LLM 路由** `LLMRoutingService` | 用各候选自己的 breaker | 候选间 fallback（非 retry） | — | ✅ 全挂 → `LLM_ROUTING_FAILED` |
| **Bifrost 网关**（启用时） | ❌ app 侧无 | ✅ 网关 `max_retries:1`/provider | ✅ provider 级（deepseek 120s） | key 级负载 / 双 key |
| **Embedding（入库/检索）** | ❌ **无** | ❌ **无** | httpx client timeout | 检索侧→普通对话；**入库侧无降级 → FAILED** |
| **Rerank** | ❌ 无 | ❌ 无 | ✅ `RAG_RERANK_TIMEOUT`(15s) | ✅ 运行期失败→原始顺序；构造失败→None（#4 已修） |
| **Tavily 外部上下文** | ❌ 无 | ❌ 无 | ✅ `EXTERNAL_CONTEXT_TIMEOUT`(6s) | ✅ 失败→空结果（静默） |
| **GrowthBook** | ❌ 无 | ❌ 无 | httpx + 30s 缓存 TTL | ✅ 失败→缓存 / 代码默认 |
| **GitHub repo 分析** | ❌ 无 | ❌ 无 | httpx timeout | token 缺失→匿名；HTTPError 抛出 |
| **Taskiq 任务（入库等）** | ❌ 无 | ❌ **无中间件** | wait-tasks-timeout 105s | mark FAILED，不重投 |
| **DB / Redis** | ❌ 无 app 级 | 连接池底层 | connect 10s | compose healthcheck |

**三条要点**：

1. **熔断全工程只有 LLM 一处**。`CircuitBreaker`（[core/circuit_breaker.py](../backend/core/circuit_breaker.py)，自带 CLOSED/OPEN/HALF_OPEN + 半开探测）是通用类，但只接进了 [pydantic_ai_service.py](../backend/ai/providers/llm/pydantic_ai_service.py)；embedding / rerank / tavily / 外部 HTTP 全裸奔。
2. **重试极少**：仅 LLM 经 OpenAI SDK `max_retries`（路由内禁用、交给 fallback）+ Bifrost 网关 `max_retries:1`。应用层无 tenacity / 退避 / taskiq-retry。
3. **多数靠"降级"而非"熔断/重试"**——对只读、无状态的 chat 检索链路是对的；**入库链路是例外**（熔断/重试/降级三者全无，一次失败即 FAILED 终态）。注意 breaker 状态**进程内、不跨 worker 共享**（`--workers 2` → 各进程一个 breaker）。

---

## 6. 当前已知薄弱点（现状事实）

> 现状事实；对应的决策与改进见第 7 节。

1. **LLM 单 provider 是唯一会硬失败到用户的点**：`LLM_PROVIDER` 为单一真实 provider 时，上游挂 → 熔断 → 对话报错。`resilient` 路由才有故障转移，但要求路由内所有 key 齐备且通过启动校验。
2. **知识入库无重试**：transient 故障（如 429）也会让文件直接 `FAILED`，需手动重新上传；broker 是裸 `ListQueueBroker`，无 retry 中间件。
3. **stale-ingestion sweeper 未接调度**：回收逻辑 `recover_stale_ingestions`（[knowledge_ingestion_recovery_service.py:42-63](../backend/services/knowledge_ingestion_recovery_service.py#L42-L63)）只标 `FAILED`、不重投；超时阈值 `KNOWLEDGE_INGEST_STALE_TIMEOUT_SECONDS`(1800s) 定义在 [ai_settings.py:158](../backend/config/ai_settings.py#L158)。它由 taskiq task `recover_stale_knowledge_ingestions`（[knowledge_tasks.py:70](../backend/worker/tasks/knowledge_tasks.py#L70)）包装，但代码内无 cron/scheduler 触发，需靠外部调度调用。
4. ~~**rerank 构造期空 key 风险**~~ **（已修复，#4）**：worker `get_rerank_service` 已加 try/except，构造失败记 warning（`event=worker_rerank_init_degraded`）并退回无 rerank（[worker/dependencies.py:95-123](../backend/worker/dependencies.py#L95-L123)），不再崩生成任务。配置侧仍建议：填 `secrets/ec2/dashscope_api_key.txt`，或在 `.env.ec2` 显式设 `RAG_RERANK_PROVIDER=`（置空）直到要用 rerank。
5. **无主动告警**：当前应用侧所有“告警”仍主要体现为 `logger.warning/error` 日志。`DEPLOY_ENABLE_OBSERVABILITY=true` 只能拉起本地 / 自托管的 Prometheus/Loki/Grafana 观察栈，不代表 AWS 生产环境已经具备告警投递出口。

---

## 7. 决策与改进路线

> 截至目前讨论的结论。P0 = 会硬失败到用户；P1/P2 = 韧性增强。

### 已决策 / 已完成

- **#4 rerank 构造期崩溃（P0）— ✅ 已修复**。worker `get_rerank_service` 加 try/except，构造失败记录 `event=worker_rerank_init_degraded` 并降级为无 rerank（[worker/dependencies.py:95-123](../backend/worker/dependencies.py#L95-L123)；测试 [test_worker_dependencies.py](../tests/unit/worker/test_worker_dependencies.py)）。
- **#1 LLM 单 provider SPOF（P0）— 决策：方案 A（接受为已知风险）**。
  - 不在 app 层加旁路 fallback —— 尊重"key 归 Bifrost 管"的所有权（[bifrost/README.md](../configs/bifrost/README.md)）。
  - 现有容错：Bifrost 双 key（`DEEPSEEK_API_KEY` + `DEEPSEEK_API_KEY_2`，weighted）+ 网关重试 + app 熔断。
  - **唯一待办（部署侧）**：确认 `secrets/ec2/deepseek_api_key.txt` 与 `..._2.txt` 是**两把不同**的 key（README 曾建议"只有一把就指向同值"，那样冗余是假的）。
  - 残留风险：DeepSeek **整体**宕机 → chat 短暂不可用，第一版可接受。

### 待办（按 embedding / 上线节奏）

- **#2 入库韧性（P1，随 embedding 切真实做）—— 核心是熔断而非重试**：
  - 给 embedder 包一个 `CircuitBreaker`（复用现成类，仿 LLM 接法），防 provider 宕机时"N 文件 × 重试"的**重试风暴**。
  - 配套**有界重试 + 退避**，且**只对瞬时错误**（`RAG_EMBEDDING_API_ERROR` / `GOOGLE_EMBEDDING_API_ERROR`），不重试永久错误（`*_INPUT_EMPTY` / `*_DIMENSION_MISMATCH`）。
  - 重跑安全（`replace_file_chunks` 幂等）；重试耗尽 → 保留 FAILED 终态。
- **#3 stale sweeper 接调度（P2）**：`recover_stale_knowledge_ingestions` 接 taskiq scheduler / 外部 cron；考虑改为**重投**而非只标 FAILED。与 #2 配套才完整。
- **#5 主动告警（P1，上线即需）—— 现状 / 条件 / 目标态需区分**：
  - **当前状态**：`deploy/monitoring/alert_rules.yml` 提供的是本地 / 自托管观察栈的规则定义；当前 `prometheus.yml` 无 `alerting:` 段、无 Alertmanager，且 worker 不在抓取目标内，所以这套配置不能直接视为 AWS 生产告警出口。
  - **条件成立时可用**：如果在本地或自托管环境显式启用 `DEPLOY_ENABLE_OBSERVABILITY=true`，可以使用 Prometheus/Loki/Grafana 做排障观察，但仍需额外接入告警投递链路。
  - **推荐生产目标（AWS 后端）**：backend / worker JSON logs → CloudWatch Logs → metric filters → CloudWatch alarms → SNS topic → email subscription。当前 production compose 仍使用 `json-file` logging driver，尚未选择 CloudWatch Agent、Docker `awslogs` 或 Fluent Bit，因此这条链路还不是可执行闭环。完成日志投递后，第一批信号盯 `level=CRITICAL`、`error_code=LLM_ROUTING_FAILED`、`error_code=KNOWLEDGE_FILE_INGEST_FAILED`、`event=circuit_breaker_opened`、`event=worker_rerank_init_degraded`。
  - **CSP 单独处理**：`event=csp_violation` 来自 report-only 观察流，第一阶段只用于 CloudWatch Logs 查询，不建 alarm；等噪声稳定后再决定是否加入 metric filter。
  - **自托管替代**：Grafana 11.x 内置告警（对 Loki 日志查询 + Prometheus 指标，无需额外 Alertmanager）；代价是运维 + 内存。本次生产投递闭环不接 Alertmanager。

### 后续可选（非必需）

- **#1 方案 B（仅当要扛 DeepSeek 整体宕机）**：跨家族 chat fallback 只能走 Bifrost **请求级** `fallbacks`（VK 级自动 fallback 会按 model 过滤，给不了 deepseek→gemini）。需：Bifrost 加第二个 chat provider + `LLMExtraBody` 加 `fallbacks` 字段（~2 行，[params.py](../backend/models/schemas/chat/params.py)）+ models.yaml 配 `extra_body.fallbacks`。gemini key 仍在 Bifrost，app 只发 model 名。残留：Bifrost 网关本身成为新 SPOF。

---

## 8. 复核命令

```bash
# 1) 生效的 AI provider 值（在 EC2 / APP_ENV=prod 下）
APP_ENV=prod LLM_PROVIDER=mock RAG_EMBED_PROVIDER=mock \
  uv run python -c "from backend.config.ai_settings import get_ai_settings as g; s=g(); \
  print('rerank=',repr(s.RAG_RERANK_PROVIDER),'planner=',repr(s.RAG_PLANNER_PROVIDER))"

# 2) 检查 secrets/ec2 下哪些 key 文件非空（避免构造期空 key 崩）
find secrets/ec2 -name '*.txt' -size +0c -printf '%f\n'
```

---

## 相关文档

- [deploy-ec2.md](deploy-ec2.md) — EC2 手动部署流程与 secret 准备命令。
- [../.codex/skills/project/references/secrets-and-flags.md](../.codex/skills/project/references/secrets-and-flags.md) — 新增 secret / feature flag 的代码改动规范。
