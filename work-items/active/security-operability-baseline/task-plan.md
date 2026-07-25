# 工作项计划：Security and Operability Baseline

> 机读状态（`status`、`workstreams`、`current_checkpoint`、`next_choices`、
> `open_decisions`）只保存在 `manifest.yaml`，并以它为准。
> 本文件只记录稳定叙事：为什么做、范围是什么、取舍是什么。
> 不要在这里复制状态字段。

## 目标

这个工作项的目标是为 Dewflow 建立 P0 / P1 的 production security 与 operability baseline。范围覆盖 P0 和 P1，但执行上必须拆成多个 PR，而不是做成一个过大的改动；P2 的 performance 和 architecture 项目明确不纳入本工作项。

## 对话结论

- 这个里程碑同时覆盖 P0 和 P1，但不能演变成一个 giant PR。
- production guardrails 可以立即推进，因为它们不依赖 Google / SMS auth 当前是否仍是 mock。
- Google login 和 SMS login 仍处于 mock 或尚未 production-facing，因此 login abuse protection 属于 pre-launch baseline，而不是所有其他 guardrail 的前置阻塞。
- production deployment 以 compose 为准，Kubernetes manifests 不属于本次 production acceptance path。
- supply-chain CI 应在出现 serious vulnerabilities 时直接 fail PR。
- alert delivery 的第一版应使用 AWS 托管链路：CloudWatch Logs / metric filters / alarms 负责判断，SNS email 负责触达人。
- CSP validation 应通过 thin self-hosted report sink + report-only rollout 完成；第一阶段只写结构化日志，不拦截请求，也不直接告警。
- N+1 profiling、LLM / embedding caching、token refresh / revocation、performance CI 和 business metrics 都保持在 P2 范围外。
- Supply-chain baseline 应同时覆盖 dependency scan、image scan、Dependabot hygiene 和 pinned action refs；完整 Trivy action behavior 仍以 GitHub CI 为最终验证环境。
- Auth abuse baseline 应把 `/sms/send`、`/sms/login`、`/google/callback` 分成独立 rate-limit bucket，并用手机号维度的 SMS verify failure lockout 防止验证码猜测。
- Compose fallback 中的真实 client IP readiness 通过 `RATE_LIMIT_TRUSTED_PROXY_CIDRS` 显式信任 Docker/nginx proxy 网段；如果 API 直连公网或改由外部 edge 代理，则该值必须改为空或实际可信网段。
- 已交付的 SMS rate limit、验证码失败 lockout 和真实 client IP 防护保留；当前不继续接真实 SMS provider，也不新增 SMS 生产验收、告警或恢复范围。
- 原 WS4 是 CSP 与 AWS alert delivery 的复合范围。最低 CloudWatch / SNS 告警职责已移交给 [`t1-lite-alerting-content-safety`](../t1-lite-alerting-content-safety/task-plan.md)；CSP report-only / enforcement rollout 继续归 T2-6，不在本工作项扩展。

## Workstream 拆分理由

### WS1 — PR 1 Production security guardrails

- Scope：对默认 production `SECRET_KEY` 执行 runtime fail-closed，关闭 production API docs，保留并验证 production mock-auth rejection，并补 focused config tests。
- Reason：高影响的 production misconfiguration 应尽早 fail，而不是在不安全状态下静默运行。
- Expected effect：production 不能使用已知 JWT signing secret 启动，mock auth 不能混入 production，public API schema browsing 也不会暴露。

### WS2 — PR 2 Authentication rate limiting and true client IP readiness

- Scope：实现 `/sms/login` rate limiting、phone-level SMS verification failure counting 或 temporary lockout、`/google/callback` rate limiting、compose / nginx `RATE_LIMIT_TRUSTED_PROXY_CIDRS` 配置，以及 deployment documentation。
- Reason：只限制 send-code 并不能阻止 verification-code abuse；而在 compose production 中，如果 proxy IP 处理不正确，rate limit key 也没有意义。
- Expected effect：在正式上线前，SMS code guessing 和 callback abuse 会被约束，compose production 的 rate-limit key 也会代表真实 client，而不是共享 proxy bucket。

### WS3 — PR 3 Supply-chain security CI

- Scope：加入 Python dependency vulnerability scanning、container image CVE scanning、Dependabot configuration、PR 与 scheduled triggers，以及对 serious vulnerabilities 直接 fail 的阈值。
- Reason：现有 CI 覆盖 lint / type / test / smoke，但尚未覆盖 dependency 与 image CVE。
- Expected effect：有问题的 dependencies 和 base images 能在 merge 前或固定周期内被发现。

### WS4 — PR 4 CSP report-only and AWS alert delivery

- Scope：保留原先关于 report-only CSP、thin CSP report sink 和 CloudWatch / SNS 的计划判断作为历史记录；不在本工作项继续实现复合 PR。最低告警由新 T1-Lite work item 接手，CSP report-only / enforcement rollout 留给 T2-6。
- Reason：告警与 CSP 已形成两个独立停止线。继续绑定会让受控内测告警被前端 enforcement rollout 阻塞，也会与新的 T1-5A / T1-6 责任重复。
- Expected effect：既有实现和决策历史不丢失；新告警计划只有一个 owner，未来 CSP 收敛也能独立验收。

## 暂缓 / 不纳入范围

- N+1 query profiling。
- LLM / embedding response caching。
- Token refresh and revocation。
- Performance CI。
- Business metrics。
- Kubernetes production manifests。
- CSP report-only 与 enforcement rollout；统一留给 T2-6 重新排期和验收。
- 自托管 Alertmanager；除非后续决定生产长期运行自托管 Prometheus alert delivery。
- 真实 SMS provider 接入、SMS 生产验收、专项告警和恢复。
- T1-5B 的 RDS / S3 / EC2 / Tunnel / secret 恢复实证和 RPO / RTO。

## Open Decisions 说明

当前工作项没有继续阻塞执行的 open decision。最低告警沿用现有 AWS CLI / CloudWatch / SNS 资产，不在 T1-Lite 引入 IaC；CSP report-only / enforcement rollout 作为 T2-6 的独立范围重新排期。
