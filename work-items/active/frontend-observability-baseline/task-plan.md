# 工作项计划：Frontend Observability and Measurement Baseline

> 机读状态（`status`、`workstreams`、`current_checkpoint`、`next_choices`、
> `open_decisions`）只保存在 `manifest.yaml`，并以它为准。
> 本文件只记录稳定叙事：为什么做、范围是什么、取舍是什么。
> 不要在这里复制状态字段。

## 目标

这个工作项的目标是补齐 frontend 可观测性缺口、纠正迁移基线文档，并建立 bundle 与 Web Vitals 的测量基线。它不是 T0 线上救火，而是一次监控、可观测性、文档和性能测量基线的完善；product rich-text、token storage、Sentry 和 stream retry 相关工作明确不纳入本次范围。

## 对话结论

- 已确认范围只包含 frontend quality review 中的 #1、#2、#3 三项。
- #1 是最高优先级缺口：当前 telemetry 能看到普通 API 5xx 失败，但看不到 render crash、全局 client error、unhandled promise 和 chat stream failure。
- #2 属于低风险文档卫生，目的是避免后续工作继续基于过时的 migration baseline 做判断。
- #3 应先测量、后优化；bundle analysis 和 Web Vitals 先建立基线，再决定后续性能动作。
- Web Vitals 应使用 metrics 语义，不能混进只记录 error 的 telemetry log。
- Migration baseline 需要反映 Zustand、TanStack Query、stream client、frontend CI 和 standards docs 的真实归属，避免后续继续基于过时清单规划。

## Workstream 拆分理由

### WS1 — Telemetry event semantics

- Scope：定义 telemetry pipeline 中 API error、client error、chat stream failure 和 Web Vitals metrics 的区分方式。
- Reason：当前 `/telemetry/errors` 的行为主要面向带 request ID 的 API 5xx 报告，而 client error 与 metrics 需要不同字段和日志语义。
- Expected effect：后续 telemetry 可搜索、可聚合，且不会把性能 metrics 混进 error log。

### WS2 — Client error and chat stream observability

- Scope：增加 application error boundary、global error handlers、unhandled promise handling，以及 chat stream failure reporting。
- Reason：这些是当前最主要的 frontend 可见性缺口；chat 是核心产品流，render crash 目前可能在没有 telemetry 的情况下直接失败。
- Expected effect：frontend crash 和 stream failure 能被看见，同时保留现有面向用户的失败处理与 retry 行为。

### WS3 — Migration plan synchronization

- Scope：更新 `frontend/docs/migration-plan.md`，反映已经完成的 Zustand、TanStack Query、stream module、frontend CI 和 standards work。
- Reason：该文档此前把已经完成的工作写成 pending，可能误导后续实现选择。
- Expected effect：人和 agent 在后续规划中都基于真实的 frontend baseline。

### WS4 — Performance and bundle baseline

- Scope：增加 bundle visualizer 输出，以及 LCP、INP、CLS 等 Web Vitals reporting。
- Reason：route lazy loading 和 manual chunks 已经存在，下一步应是测量而不是继续做推测式优化。
- Expected effect：后续性能优化决策可以基于真实的 bundle 组成和 real-user performance metrics。

### WS5 — Focused validation and handoff

- Scope：运行针对 telemetry、文档和 build / measurement 输出的 targeted tests 或 checks。
- Reason：这个工作项涉及横切的 observability 路径，需要留下清晰 checkpoint 供后续 review 或继续推进。
- Expected effect：这套 baseline 可以进入交付或评审状态，且 deferred 决策仍保持明确分离。

## 暂缓 / 不纳入范围

- Chat Markdown rendering 和 sanitization。
- JWT localStorage → HttpOnly cookie migration。
- Sentry integration。
- Chat stream auto-reconnect 或 resume。
- Micro-frontends、design system work、broad refactors 或 coverage-chasing。

## Open Decisions 说明

- `telemetry-event-semantics`：在实现 client error 和 Web Vitals 之前，先决定 endpoint 或 payload shape，保证日志继续保持清晰的 error-vs-metric 语义。
