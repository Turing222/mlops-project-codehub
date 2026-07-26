# WS4 — Performance and Bundle Baseline 实现计划

> 本文件是 WS4 的可执行实现计划，供新会话直接据此开工。
> 机读状态仍以 `manifest.yaml` 为准；本文件只描述「怎么做」。
> 启动方式：先读 `.codex/skills/project/SKILL.md`，再按需加载 `write` / `edit` / `add-tests` skill。

## Context

WS4 的目标是建立**性能测量基线**，而非做推测式优化（measure-first）。两件事：

1. **Bundle composition 分析** —— 看清各 chunk / 依赖体积占比。
2. **Web Vitals 采集**（LCP / INP / CLS，可含 FCP / TTFB）—— 拿到真实用户性能指标。

强约束（来自 WS1 已定的 telemetry 语义）：
- Web Vitals 是 **metric 语义，绝不能混进 `/api/v1/telemetry/errors`**（那是 error log，`severity` 固定 `error`、日志事件 `frontend_error_reported`）。
- WS4 必须走**独立 metrics 通道**（既定方向：`/api/v1/telemetry/metrics`），日志事件独立为 `frontend_metric_reported`。

现状（已核实）：
- `frontend/apps/admin/vite.config.ts` 已配 `build.rollupOptions.output.manualChunks`，但**没有** bundle visualizer。
- `web-vitals`、`rollup-plugin-visualizer` 均**未安装**。
- 后端 ingestion 端点范式可直接复用：`telemetry_api.py`、`csp_report_api.py`（origin guard + `204` + 结构化日志 + 不落库）；限流配置在 `backend/config/web_settings.py:132-135`。

## Recommended Approach

### 1. Bundle visualizer（构建期分析，零运行时影响）

- 安装：`pnpm -C frontend/apps/admin add -D rollup-plugin-visualizer`。
- 在 `vite.config.ts` 用 env gate 接入（避免影响常规 build）：仅当 `process.env.ANALYZE` 为真时加入 `visualizer({ filename: 'dist/stats.html', gzipSize: true, brotliSize: true })`。
- 用法：`ANALYZE=1 pnpm -C frontend/apps/admin build` → 产出 `dist/stats.html`。
- 备注：visualizer 大概率会暴露现有 `manualChunks` 的匹配顺序问题（`id.includes('react')` 会先于 `react-router` 命中，把 router 误并入 `react-vendor`）。**先记录、暂不优化**——chunk 调整属测量之后的独立决策。

### 2. 后端 metrics ingestion 端点（与 error 通道语义分离）

新增 `POST /api/v1/telemetry/metrics`。两种落点，二选一：
- **(推荐) 同 router 加端点**：在 `telemetry_api.py` 内新增 `report_frontend_metric`，复用现有 `frontend_telemetry_limiter` 与 origin guard。改动小、范围聚焦。
- 独立 `metrics_api.py` + 独立 limiter：语义更干净，但要新增 router wiring 与配置。

Schema（独立于 `FrontendErrorTelemetry`）：
- `name`: 枚举 `LCP | INP | CLS | FCP | TTFB`（用 `StrEnum`）。
- `value`: `float`（必填）。
- `rating`: 枚举 `good | needs-improvement | poor`。
- `id`: web-vitals 的指标实例 id（去重/排查用）。
- `navigationType?`、`url?`（≤2048）、`page?` 可选。
- 日志事件 `frontend_metric_reported`，字段前缀 `frontend_metric_*`，**不要**复用 error 字段名。

保持不变：origin check、`204` 响应、router rate-limit、不落库。

### 3. 前端 metrics reporter（独立于 error telemetry）

- 安装：`pnpm -C frontend/apps/admin add web-vitals`（v4：用 `onLCP`/`onINP`/`onCLS`/`onFCP`/`onTTFB`；INP 已取代 FID，**不要用 FID**）。安装时用 context7 / npm 确认当前 API。
- 新建 `frontend/apps/admin/src/lib/observability/web-vitals.ts`：
  - 导出 `registerWebVitals()`，内部注册 `onLCP/onINP/onCLS/...` 回调，把每条指标 `POST` 到 `API_URLS.TELEMETRY.METRICS`（需在 `api/urls.ts` 新增）。
  - 传输复用 `sendBeacon → fetch keepalive` 模式（可从 `telemetry.ts` 抽一个共享 `beaconPost(url, payload)`，或独立实现；**但不要**调用 `reportFrontendErrorEvent`，语义不同）。
  - 幂等注册（参考 `global-error-handlers.ts` 的 window 级标记）。
- 在 `main.tsx` bootstrap 调 `registerWebVitals()`（与 `registerGlobalErrorHandlers()` 并列）。

### 4. 待确认决策（开工前定）

- metrics 端点落点：同 router 加端点（推荐）还是独立 `metrics_api.py`。
- 采样策略：第一版建议**全量上报**（流量低，先拿全貌），后续再按需抽样。
- INP / CLS 在 SPA 路由切换下的上报时机：评估 web-vitals 的 `reportAllChanges` 与页面生命周期，避免单页应用下漏报或重复。
- 是否需要在 metrics payload 带路由维度（`page`），便于按页面聚合。

## Critical Files

### Frontend
- `frontend/apps/admin/vite.config.ts`（visualizer，env gate）
- `frontend/apps/admin/package.json`（`web-vitals`、`rollup-plugin-visualizer`）
- `frontend/apps/admin/src/lib/observability/web-vitals.ts`（新建）
- `frontend/apps/admin/src/api/urls.ts`（新增 `TELEMETRY.METRICS`）
- `frontend/apps/admin/src/main.tsx`

### Backend
- `backend/api/v1/endpoint/telemetry_api.py`（新增 metrics 端点）或新建 `metrics_api.py`
- `backend/api/v1/api.py`（若独立 router 才需 wire）
- `backend/config/web_settings.py`（如独立限流，新增 `FRONTEND_METRICS_RATE_LIMIT_*`）

## Test Plan

### Frontend
- 新增 `web-vitals.ts` 测试：mock `web-vitals` 的 `onLCP/onINP/onCLS`，断言每条指标 `POST` 到 metrics URL、payload 形状（name/value/rating/id）正确、传输走 sendBeacon→fetch fallback、幂等注册不重复。

### Backend
- 新增 metrics 端点 component 测试（参考 `tests/component/api/test_telemetry_api.py`）：合法指标返回 `204` 且日志事件为 `frontend_metric_reported`；非法 `name`/`rating` 返回 `422`；缺 `value` 返回 `422`；origin guard 与 forwarded-proto 同源逻辑保持。

### Bundle
- `ANALYZE=1 pnpm -C frontend/apps/admin build` 能产出 `dist/stats.html`（手动或 CI 验证；常规 build 不受影响）。

## Verification

1. 前端 targeted vitest（web-vitals reporter）+ 后端 metrics component 测试全绿。
2. `ANALYZE=1` build 产出 `stats.html`，记录 top chunks 体积基线。
3. 手动触发页面加载/导航，确认 `/api/v1/telemetry/metrics` 收到 LCP/CLS/INP，且 `/errors` **没有**混入任何 metric。
4. 后端日志中 `frontend_metric_reported` 与 `frontend_error_reported` 清晰分离。

## Out of Scope

- 实际性能优化（拆包、预加载等）——先测量，优化是后续独立决策。
- Sentry、第三方 RUM SaaS、长期 metrics 存储/看板。
- 把 Web Vitals 混入 error telemetry。

## 衔接

WS4 完成后解锁 WS5（focused validation and handoff）：跑通 telemetry / 文档 / build & measurement 的 targeted 检查，留收尾 checkpoint。完成实现后按 `handoff.md` 追加 Change Summary，并把本工作项的 manifest 状态同步（WS4 → done）。

## 实现结果（2026-06-08 实测）

### 决策落地（4 项待确认决策按推荐默认收敛）
- metrics 端点：**同 router 加端点**——`telemetry_api.py` 内新增 `report_frontend_metric`（`POST /api/v1/telemetry/metrics`），复用 `frontend_telemetry_limiter` 与 `is_allowed_browser_origin`；同步改写模块 docstring 边界（原文「不承担 metrics/Web Vitals」已更新为「错误与指标走各自独立 schema/日志事件」）。
- 采样：**全量上报**。
- SPA 上报时机：用 web-vitals 默认 `reportAllChanges=false`（页面隐藏时报终值），不做自定义节流。
- 路由维度：payload **带 `page`**（`window.location.pathname`）+ `url`（`href`，≤2048）。

### 版本修正
- 计划假设 `web-vitals` v4，实际安装 **v5.3.0**：`onLCP/onINP/onCLS/onFCP/onTTFB` 与 `Metric` 形状不变、FID 已彻底移除，意图一致。`navigationType` 6 个取值（含 `back-forward-cache`/`prerender`/`restore`）在后端**枚举完整**，避免合法指标被判 `422`。
- `rollup-plugin-visualizer` 安装 **7.0.1**（devDep）。

### Bundle 基线（`ANALYZE=1 vite build`，gzip）
| chunk | raw | gzip |
| --- | --- | --- |
| antd-vendor | 775.3 kB | 250.5 kB |
| react-vendor | 252.7 kB | 82.4 kB |
| vendor | 175.8 kB | 55.5 kB |
| index（主包） | 127.1 kB | 39.0 kB |
| query-vendor | 33.1 kB | 9.7 kB |

**已确认 manualChunks 顺序 bug**：构建产物中**没有 `router-vendor` chunk**——`id.includes('react')` 先于 `react-router` 命中，把 router 并入了 `react-vendor`。按 measure-first 原则**先记录、暂不修**（拆包属测量后的独立决策）。

### 验证
- 前端：full vitest 185 passed（含 `web-vitals.test.ts` 5 条与重构后的 `telemetry.test.ts`）、`tsc -b` 通过、eslint 无新增告警；`ANALYZE=1` build 产出 `dist/stats.html`。
- 后端：`tests/component/api/test_telemetry_api.py` 14 passed（8 error + 6 metric）、ruff check + format 通过。
