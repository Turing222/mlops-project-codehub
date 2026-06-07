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

- Scope：为 frontend delivery surface 增加 report-only CSP，增加 thin self-hosted CSP report sink，只写 `event=csp_violation` 结构化日志；生产告警投递改走 CloudWatch Alarm -> SNS email，优先覆盖 backend / worker critical logs、关键 failure events 和 AWS 主机资源告警。
- Reason：CSP enforcement 容易误伤前端，应先用 report-only 建立真实 allowlist；当前最大 operability 缺口不是缺少更多 Prometheus rules，而是 production incident 不能可靠触达到人。AWS 后端 + Cloudflare Pages 前端的部署形态下，CloudWatch / SNS 比自托管 Alertmanager 更贴近生产 source of truth，也减少 EC2 上额外运维负担。
- Expected effect：CSP 可以在不影响线上功能的前提下积累 validation 数据；生产告警通过 AWS 托管链路触达 email receiver，后续服务器性能告警和前端安全信号可以复用同一投递路径。

## 暂缓 / 不纳入范围

- N+1 query profiling。
- LLM / embedding response caching。
- Token refresh and revocation。
- Performance CI。
- Business metrics。
- Kubernetes production manifests。
- CSP enforcement；待 report-only 日志稳定后再决定是否启用阻断。
- 自托管 Alertmanager；除非后续决定生产长期运行自托管 Prometheus alert delivery。

## Open Decisions 说明

- `aws-alert-infra-owner`：需要确认 CloudWatch Logs、metric filters、alarms 和 SNS topic 先在 AWS 控制台 / CLI 手工建立，还是后续补 IaC 管理。
- `csp-enforcement-rollout`：CSP enforcement 暂缓；只有 report-only 日志证明 allowlist 稳定后才进入阻断 rollout。
