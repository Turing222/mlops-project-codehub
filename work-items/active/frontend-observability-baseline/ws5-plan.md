# WS5 — Focused Validation and Handoff 实现计划

> 本文件是 WS5 的可执行实现计划，供新会话直接据此开工。
> 机读状态仍以 `manifest.yaml` 为准；本文件只描述「怎么做」。
> 启动方式：先读 `.codex/skills/project/SKILL.md`，再按需加载 `read` / `edit` skill。

## Context

WS5 是本工作项的收尾 workstream：对前面落地的横切 observability / measurement 路径做**聚焦验证**，并留下清晰的交付 / 评审 checkpoint。它 `deps: [2, 3, 4]`，三个依赖现已全部 `done`，WS5 已解锁。

WS5 **不引入新功能**，只做三件事：
1. **聚焦验证** —— 用仓库既有的 targeted 检查证明 telemetry / 文档 / build & measurement 三条路径都成立。
2. **文档同步收口** —— WS4 落地后，`migration-plan.md` 又把已完成的「测量基线」列成待办，需小幅同步（呼应 completion_chain：不再把已完成工作写成 pending）。
3. **交付 handoff** —— 确认 deferred 项仍在范围外，记录最终 checkpoint，把 baseline 推进到可交付 / 评审状态。

本会话已实跑掉大部分验证，可直接复用结论（见下「现状」）。

现状（本会话已验证）：
- 前端 full vitest **187 passed**（28 files），含 `telemetry.test.ts`、`web-vitals.test.ts`、`global-error-handlers.test.ts`、`AppErrorBoundary.test.tsx`、`chat-stream.test.ts`、`use-chat-controller.test.tsx`、`streaming-contract.test.tsx`、`query-client.test.ts`；`tsc -b` 通过；eslint 0 errors（唯一 warning 在 `GoogleCallbackPage.tsx`，既有、与本工作项无关）。
- 后端 `tests/component/api/test_telemetry_api.py` **14 passed**（8 error + 6 metric）；`ruff check` + `ruff format --check` 通过。
- `ANALYZE=1` build 产出 `dist/stats.html`，bundle 基线已记入 `ws4-plan.md`。
- error 与 metric 通道分离已被测试锁定：`web-vitals.test.ts` 断言指标只发往 `TELEMETRY.METRICS`、绝不命中 `ERRORS`；后端 metric 测试断言不产出 `frontend_error_reported`。

WS5 待补的，主要是**仓库口径的整链验证**（用 `make` target，而非散跑）、`ty` 后端类型检查（本会话仅跑了 `ruff`）、**文档同步**与 **handoff**。

## Recommended Approach

### 1. 前端聚焦验证（仓库口径）

用 Makefile 的整链 target，而非散跑单测：

```bash
make frontend-check      # = frontend-lint + frontend-typecheck + frontend-test + frontend-build
```

测量输出单独验一次（常规 build 不带 visualizer）：

```bash
ANALYZE=1 pnpm -C frontend/apps/admin build   # 产出 dist/stats.html
```

可选（CI PR gate 会跑，本地确认更稳）：

```bash
make frontend-e2e-mock   # playwright mock e2e
```

观测重点：observability 测试清单（telemetry / web-vitals / global-error / AppErrorBoundary / chat-stream / use-chat-controller / streaming-contract / query-client）全绿，`frontend-build` 与 `ANALYZE` build 均成功。

### 2. 后端聚焦验证（含本会话漏跑的 `ty`）

```bash
make qa-test-component COMPONENT_TARGETS=tests/component/api/test_telemetry_api.py
make qa-lint            # ruff check .
make qa-format-check    # ruff format --check .
make qa-typecheck       # uv run ty check .  ← 本会话只跑了 ruff，ty 需补
make qa-boundaries      # import 边界（确认新端点未越层）
```

可选（确认新端点未波及其它套件，对齐 PR gate 后端口径）：

```bash
make qa-test-ci         # DEWFLOW_TEST_PROFILE=ci pytest -m "not performance and not local_only and not requires_llm and not requires_s3"
```

### 3. 文档同步收口（WS3 在 WS4 落地后的回填）

WS4 落地后，`frontend/docs/migration-plan.md` 仍把测量基线列为待办，需小幅同步（**仅描述既成事实，不改迁移结论**）：
- L27 附近「当前剩余收口点」首条「Web Vitals 与 bundle composition 还缺少测量基线」→ 改为已完成，并点明 Web Vitals 走独立 `/telemetry/metrics` 通道、bundle 用 `ANALYZE` visualizer。
- L283 附近「推荐执行顺序」第 3 项「测量基线：增加 bundle visualizer 和 Web Vitals baseline」→ 标记（已完成），与上面 1、2 项同款式。
- 「已完成」清单（L11-24）可补一行：Web Vitals metrics 通道与 bundle visualizer 基线已建立。

落点用 `edit` skill；改动控制在状态字句，不重写阶段叙事。

### 4. 横切不变量复核（error vs metric 分离）

确认端到端两条通道语义不混：
- `/api/v1/telemetry/errors` 只收 error event（日志 `frontend_error_reported`、`severity` 固定 `error`）。
- `/api/v1/telemetry/metrics` 只收 Web Vitals（日志 `frontend_metric_reported`、字段前缀 `frontend_metric_*`）。
- 已由 §1/§2 的测试覆盖；无需新增测试，validation 时复述结论即可。

可选 manual smoke（需本地起 backend，按 CLAUDE.md 用 `curl` 不浏览 localhost）：
```bash
curl -i -X POST localhost:8000/api/v1/telemetry/metrics -H 'Content-Type: application/json' \
  -d '{"name":"LCP","value":2300.4,"rating":"good","id":"smoke-1","navigationType":"navigate"}'   # 期望 204
```

### 5. Out-of-scope 护栏复核

确认 deferred 项**没有悄悄混入**本工作项改动：
- 无 `@sentry/*` 依赖新增（`rg -n "sentry" frontend/apps/admin/package.json`）。
- 无 chat markdown 渲染 / sanitization、无 JWT localStorage→cookie 迁移、无 chat stream 自动重连 / resume。
- 这些在 `task-plan.md`「暂缓 / 不纳入范围」已声明；validation 只需确认 diff 未触碰。

### 6. Handoff / checkpoint

全部验证通过后：
- `manifest.yaml`：WS5 `status` → `done`；`current_checkpoint` 推进为收尾态（建议 name `observability-baseline-validated`，state `validated`），summary 记录五个 workstream 全部 done + 验证口径；`next_choices` 收敛为「交付 / 提 PR」。
- 顶层 `status: active → done` 与是否归档目录：属外向收尾动作，**开工前与用户确认**（PR 由用户手动提交，manifest 状态反映工作完成而非合并）。
- 按 `handoff.md` 追加 Change Summary。

## Critical Files

- `frontend/docs/migration-plan.md`（§3 文档同步，唯一代码外改动）
- `work-items/active/frontend-observability-baseline/manifest.yaml`（§6 WS5 → done、checkpoint）
- 验证只读涉及：`Makefile`、`tests/component/api/test_telemetry_api.py`、`frontend/apps/admin/src/lib/{http,observability}/**`

## Test Plan

WS5 以**运行既有检查**为主，不新增测试（除非验证暴露缺口）：
- 前端：`make frontend-check` + `ANALYZE=1` build；可选 `make frontend-e2e-mock`。
- 后端：`make qa-test-component`（telemetry）+ `qa-lint` + `qa-format-check` + `qa-typecheck` + `qa-boundaries`；可选 `qa-test-ci`。
- 文档：人工复读 `migration-plan.md` 同步后是否还把已完成项列为 pending。

## Verification

1. `make frontend-check` 全绿；`ANALYZE=1` build 产出 `dist/stats.html`。
2. 后端 telemetry component 全绿；`ruff` / `ty` / `qa-boundaries` 通过。
3. `migration-plan.md` 不再把测量基线列为待办；completion_chain 第 2 条成立。
4. error / metric 两通道日志事件清晰分离（复述测试结论）。
5. out-of-scope 项确认未混入 diff。
6. `manifest.yaml` 五个 workstream 全 `done`，checkpoint 记录交付态。

## Out of Scope

- 任何新功能或性能优化（拆包、`router-vendor` 修复等——见 `ws4-plan.md`，属测量后的独立决策）。
- Sentry、第三方 RUM、长期 metrics 存储 / 看板。
- Chat markdown / sanitization、JWT cookie 迁移、stream 自动重连。
- 把顶层工作项 `status` 翻 `done` 或归档目录前，未经用户确认不擅自执行。

## 衔接

WS5 完成即本工作项收尾：五个 workstream 全部 `done`，baseline 进入可交付 / 评审状态，deferred 决策保持明确分离。后续性能优化（含 `router-vendor` 拆包）作为**新工作项**另起，不在本工作项内继续扩张。

## 验证结果（2026-06-08 实测）

### 本工作项改动：全绿
- 前端 `make frontend-check`：lint（0 errors）+ `tsc -b` + vitest **187 passed**（28 files）+ production build 均通过；`ANALYZE=1` build 产出 `dist/stats.html`。
- 后端：`make qa-test-component`（telemetry）**14 passed**；改动文件 `ruff check` / `ruff format --check` / `ty check` 全干净；`make qa-boundaries` 全过（新端点未越层）。
- out-of-scope 护栏：仅新增 `web-vitals` + `rollup-plugin-visualizer` 两个依赖；无 `@sentry`、无 markdown/dompurify/js-cookie/sanitize；diff 未触碰 JWT cookie / stream 重连。
- 文档：`migration-plan.md` 已把测量基线从「待办」回填为「已完成」（3 处），completion_chain 第 2 条成立。

### Pre-existing 债（与本工作项无关，未处理）
- 仓库口径 `make qa-lint` 报 1 个 ruff error、`make qa-format-check` 6 个文件待格式化，**全部落在未改动文件**：`worker_generation_workflow.py`、`client_ip.py`、`knowledge_repo.py`、`test_auth_api.py` 等。
- 这些不在本工作项 diff 内、不由 WS5 引入；在此处修会污染本次 diff、扩大范围。留作独立的仓库卫生任务。

### Handoff
- `manifest.yaml`：五个 workstream 全 `done`；checkpoint `observability-baseline-validated` / `validated`。
- 顶层 `status: active → done` 与目录归档属外向收尾，待用户确认后再动（PR 由用户手动提交）。
