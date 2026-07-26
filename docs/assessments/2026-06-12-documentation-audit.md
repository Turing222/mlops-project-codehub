# 文档贴切度审计报告

> 日期：2026-06-12
> 范围：仓库内全部项目文档与当时的代码、目录结构和 `Makefile`
> 性质：时点审计，不属于长期规范
> 证据基线：76 个 `.md` 文件的机械扫描与分簇语义核对
> 状态：冻结；后续现行约定以 `docs/README.md` 及各长期目录为准

## 范围与方法

- **范围**：仓库内全部项目文档（76 个 `.md`，排除 `.venv/`、`.git/`、`.pytest_cache/`、`node_modules/`）。
- **机械核对**（脚本全量扫描）：
  - 内部 Markdown 链接目标是否存在；
  - 文档引用的 `make <target>` 是否在 `Makefile` 中定义；
  - README 启动命令引用的模块/路径/符号（`backend.main:app`、`broker`、taskiq 任务模块、`docker-compose.db.yml` 等）是否存在。
- **语义核对**（分簇交叉验证文档论断 vs 实际代码）：前端簇、后端簇、部署/运维簇、测试/评测/性能簇。
- **复核**：对发现项逐条用 `ls`/`grep` 实测确认，不只依赖二手结论。

## 总体结论

整体质量高，**没有断链、没有失效的 make 目标、没有失效的启动命令**。根 `README.md`、`docs/README.md` 索引、部署/运维全簇、测试/评测/性能全簇均准确。漂移集中在**前端 `architecture.md`/`migration-plan.md` 的目录示例**（与实际 `src/` 结构不符）和**少量后端文档的细节陈述**。无 high 级"会导致照做即错"的命令类问题；前端目录漂移定为 high，因为会误导新贡献者按错误结构建文件。

| 维度 | 结果 |
| --- | --- |
| 内部链接 | ✅ 0 断链 |
| `make` 目标引用 | ✅ 具名目标全部存在（仅余 `frontend-*` 等通配写法） |
| README 启动命令 | ✅ 模块/路径/符号全部存在 |
| 部署/运维簇（15 篇） | ✅ 全部准确 |
| 测试/评测/性能簇 | ✅ 命令、模块、marker 全部存在 |
| 前端簇 | ⚠️ `architecture.md` / `migration-plan.md` 目录漂移 |
| 后端簇 | ⚠️ legacy README + 2 处细节 |

## 机械核对结果（全部通过）

- 全量文档内部链接：**0 断链**。
- `make` 引用 76 个 → 具名目标全部命中；`comm` 余下仅 `frontend-`、`qa-`、`env-smoke-`、`deploy-ec2-` 四个**通配前缀**（源于 `make frontend-*` 这类写法，各前缀分别有 11/27/7/7 个真实成员）。
- README 启动链：`backend/main.py`（`app = FastAPI(` @60）、`backend/infra/task_broker.py`（`broker = ListQueueBroker(` @16）、三个 worker 任务模块、`docker-compose.db.yml`、`frontend/apps/admin/` 均存在。

## 发现明细（按簇）

严重度定义：**high** = 照文档做会出错 / 误导结构或命令；**med** = 陈旧但无害；**low** = 细节不精确。

### 前端簇

#### frontend/docs/architecture.md — ⚠️ 目录示例与实际 `src/` 漂移

实际 `frontend/apps/admin/src/` 结构为扁平布局：`api/ components/ context/ features/ lib/ pages/ query/ schemas/ stores/ streams/ test/ types/ utils/`，无 `app/` 包裹层。

- **[high，已处理]** 推荐目录示例（architecture.md:119-157）曾使用 `app/router/`、`app/providers/`、`queries/`（复数）、`ui-store.ts`、`lib/dayjs/`、`lib/http/interceptors.ts` 等不存在结构；当前已对齐实际 `src/` 扁平布局与 `query/` 单数目录。
- **[med，已处理]** `queries/`（复数，architecture.md:140）实际为 `src/query/`（单数）。
- **[med，已处理]** `lib/http/interceptors.ts`（architecture.md:128）不存在；请求拦截逻辑写在 `src/lib/http/client.ts` 内。
- **[low，已处理]** `ui-store.ts`（architecture.md:139）实际为 `src/stores/theme-store.ts`（另有 `auth-store.ts`）。
- **[low，已处理]** `lib/dayjs/index.ts`（architecture.md:131-132）不存在，`dayjs` 也不在 `package.json` 依赖中。

> 实测：`ls src/` 确认无 `app/`、为 `query/` 单数；`stores/` 仅 `theme-store.ts`+`auth-store.ts`；`grep dayjs package.json` 无命中。

#### frontend/docs/migration-plan.md — ⚠️

- **[high，已处理]** Phase 3 scope（migration-plan.md:116-119）曾让读者创建 `src/queries/`（复数）下的文件；当前已改为 `src/query/query-client.ts`、`src/query/hooks/{auth,users,chat}.ts` 和 `src/query/keys/{auth,users,chat}.ts`。

#### frontend/docs/standards/testing.md — ⚠️

- **[low，已处理]** testing.md:59 曾把 `src/test/mock-data` 表述为目录（"中的基础响应数据"），实际是单文件 `src/test/mock-data.ts`。

#### 前端其余 — ✅ 准确

- `frontend/apps/admin/README.md`：命令与 `package.json` scripts、Makefile `frontend-*` 目标一致。
- `frontend/docs/README.md`、各 `standards/*.md`（api/components/state/streaming/styling）、`.codex/skills/project/references/frontend.md`：技术栈版本与 `package.json` 一致，正确使用 `src/query/` 单数。

### 后端簇

#### docs/legacy/backend-overview-legacy.md — ⚠️ 旧版保留副本，存在陈旧

- **[med，已处理]** legacy README:320 对 `/metrics` 的描述不完整：实际同时存在根路径 `GET /metrics` 探针（`backend/main.py:101`）和前端指标上报 `POST /api/v1/telemetry/metrics`（`backend/api/v1/endpoint/telemetry_api.py:148` 经 `prefix="/telemetry"` 挂载）。
- **[low，已处理]** ORM 表清单不全：现已存在但 legacy 未列出的表包括 `credit_accounts`、`credit_transactions`、`repo_analysis_results`、`repo_analysis_runs`、`usage_records`。核心表仍准确，属增量陈旧。
- 说明：该文件本就标注为"旧版根 README 保留副本"，以上为其陈旧程度量化，非新错误。

#### docs/todos/storage-column-types.md — ⚠️ 待办未落地

- **[med]** 文档描述把 `file_path`/`storage_key` 从 `String(1024)` 改为 `Text` 的迁移待办；实际 `backend/models/orm/knowledge.py:81,89` 仍为 `String(1024)`，迁移**未创建/未应用**。文档说"迁移完成后删除本文件"，但文件仍在——即这是一个**真实未完成的 TODO**，文档本身准确，只是提示该项尚未推进。

#### .codex/skills/project/references/secrets-and-flags.md — ⚠️

- **[low，已处理]** secrets-and-flags.md:36-38 曾写作 `/api/v1/users/me.features`。实际 API 路径是 `/api/v1/users/me`（`backend/api/v1/endpoint/user_api.py`），返回的 `UserResponse` 含 `features` 字段。`.features` 是前端取值写法，不是 URL 后缀，记法易误读。

#### 后端其余 — ✅ 准确

- `async-default-style.md`、`backend-interface-style.md`、`sqlalchemy-async-pitfalls.md`、`api-keys-and-degradation.md`、`automation-standard.md`、`api-review-checklist.md`、`static-test-node.md` 均与代码一致。
- `.codex/skills/project/references/architecture.md`：web/worker 拆分、3-tier 调用链、依赖注入规则经抽查均成立；`coding.md`、`config-policy.md` 准确。

### 部署 / 运维簇 — ✅ 全部准确

`docs/platform/deploy-ec2.md`、`docs/platform/deploy-hardening-backlog.md`、`docs/platform/k8s-scaling-strategy.md`、`docs/platform/frontend-delivery-and-edge-responsibilities.md`、`docs/workflows/dev-test-flow.md`，以及 `deploy/k8s/**`、`deploy/monitoring/**`、`local/observability/`、`secrets/{ec2,local-prod,smoke}/`、`configs/bifrost/` 全部 README：
- 引用的文件路径、make 目标、Docker/compose 配置、env 变量名、secret 文件名、CloudWatch 指标/告警名、k8s manifest 引用均与实际资产一致。
- `deploy-hardening-backlog.md` 准确反映"完成即删"约定，当前所列为真实待办。

### 测试 / 评测 / 性能簇 — ✅ 全部准确

- `docs/README.md`（索引）：阅读路径与分类索引链接全部解析成功。
- `tests/README.md` 引用的 `make qa-test-*`/`flow-runtime`/`qa-eval-*`/`qa-perf-chat` 等目标全部存在；`tests/CONVENTIONS.md` 的 marker（`integration` 等）与 `pyproject.toml:117` 的 `markers` 一致。
- `evals/README.md`：`eval_answer`/`eval_rag_planner`/`eval_retrieval`/`compare_reports` 模块均存在，`make qa-eval-api`/`make check` 已定义。
- `perf/README.md`：`perf/chat_api_load.py` 存在，`make qa-perf-chat`/`qa-perf-chat-locust` 已定义。

## 修复状态

> 本报告最初为只读审计；后续文档修复已按下列状态更新。

1. **已处理**：`frontend/docs/architecture.md` 目录示例已对齐实际 `src/`。
2. **已处理**：`frontend/docs/migration-plan.md:116-119` 已改为 `src/query/` 单数目录，并补齐 `hooks/` 与 `keys/` 分层。
3. **已处理**：`docs/legacy/backend-overview-legacy.md:320` 已同时列出 `GET /metrics` 和 `POST /api/v1/telemetry/metrics`。
4. **待处理**：`docs/todos/storage-column-types.md` 仍对应真实迁移待办；要么落地 `String(1024)`→`Text` 迁移后删除该文件，要么保留并确认仍有效。
5. **已处理**：`testing.md:59` 的 `mock-data` 已标注为文件；`secrets-and-flags.md:36-38` 已澄清为"`/users/me` 响应的 `features` 字段"；legacy README 的 ORM 表清单已补全。

## 维护提醒

按 `docs/README.md:85` 既有约定——**代码结构或 Makefile 入口变化时优先更新根 `README.md` 与 `docs/README.md` 索引**。本次漂移全部出现在前端目录示例类描述，建议此类"结构镜像型"内容尽量用链接指向实际目录、少手抄结构树，以降低再次漂移概率。
