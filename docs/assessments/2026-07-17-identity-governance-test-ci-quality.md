# 身份治理与测试、CI、代码质量评估

> 日期：2026-07-17
> 范围：登录方式、角色权限、Workspace、审计、Credits、Feature Flags，以及后端/前端测试覆盖、CI 门禁、慢测与 mock/真实环境比例
> 性质：只读时点评估；记录当前实现、测试证据、线上仓库治理快照与整改优先级，不代表建议已经实施
> 证据基线：分支 `chore/deps-batch-patch`、提交 `af4f855296c6`、本地运行代码，以及 2026-07-17 只读 GitHub Ruleset/Actions 快照
> 状态：冻结；后续现行约定以代码、`docs/standards/`、`docs/workflows/`、`frontend/docs/standards/` 和 GitHub 仓库设置为准

## 1. 结论速览

Dewflow 已经从单用户应用演进出完整的身份治理骨架：密码、短信和 Google 登录并存；全局 superuser 与 Workspace RBAC 分层；审计、Credits 和 Feature Flags 都有独立模型或服务。当前成熟度可概括为“基础能力完整，治理闭环不完整”。

最需要优先处理的不是继续增加功能，而是让已有机制在异常、删除、并发和发布门禁下仍然可信：

1. Workspace 软删除后，成员角色查询不校验 Workspace 活跃状态；下游资源可能继续按残留角色授权。这是代码路径支持的高风险静态推断，必须先用真实 PostgreSQL 回归测试确认。
2. Google OAuth 缺少 `state`/PKCE，空 redirect allowlist 会放行任意回调；SMS 非 mock 分支仍未接供应商；JWT 存在 localStorage，且没有服务端撤销或 refresh rotation。
3. 后端声明了 75% coverage floor，但现有 Make/CI 命令未启用 `pytest-cov`，因此该门禁没有实际执行。
4. active Ruleset 要求 `Docker smoke`，而对应 workflow 对普通业务代码 PR 不触发，存在 required check 永远等待的结构性风险。
5. 最近 100 次 Actions 样本中，Security CI 20/20 失败且不是 required check；长期红灯已经形成告警疲劳和合并盲区。

测试总量不低，但分布高度偏向隔离测试。按测试函数所在层级粗略估算，后端和前端都约为 99:1 的 mock/隔离环境对真实环境比例；真实链路价值高，但业务覆盖面窄，而且 LLM、Embedding、SMS 和 Google OAuth 仍未进入真实外部服务验证。

## 2. 范围、方法与证据边界

### 2.1 证据类型

| 证据类型 | 检查方式 | 结论边界 |
| --- | --- | --- |
| 运行代码 | 读取 endpoint、service、repository、ORM、配置和前端消费者 | 可确认当前调用链和默认行为，不等同于生产流量证明 |
| 测试资产 | 静态统计测试文件、测试函数、marker 和 E2E spec | 数量不代表风险权重；参数化展开不计入直接调用数 |
| CI 配置 | 读取 Make targets、pytest/Vitest/Playwright 配置和 workflows | 可确认声明的门禁与触发条件 |
| GitHub 快照 | 只读查询 Ruleset、classic protection 与最近 100 次 Actions | 仅代表 2026-07-17 查询时状态，不替代长期趋势监控 |
| 静态推断 | 串联软删除过滤、角色查询和下游授权路径 | 必须由真实数据库回归测试确认后再视为已复现缺陷 |

本轮没有执行完整业务测试套件，也没有调用真实 SMS、Google、LLM 或 Embedding 服务；只在文档写入后执行文档机械校验。CI 运行结果取自 GitHub 已完成记录。

### 2.2 判定口径

- **已确认**：当前代码、配置或线上只读查询直接支持。
- **静态推断**：多段代码组合后存在可达风险，但本轮未动态复现。
- **建议**：目标状态或整改方向，不表示当前已经具备。
- **真实环境**：至少运行真实应用进程与依赖基础设施；使用 mock AI provider 的 Docker/E2E smoke 不等于真实外部供应商测试。

## 3. 身份与治理域

### 3.1 总体矩阵

| 领域 | 当前能力 | 主要缺口 | 判断 |
| --- | --- | --- | --- |
| 登录 | 密码、SMS、Google OAuth；登录/注册限流；账号启用与 closed beta 门控；JWT access token | OAuth 会话绑定、SMS 生产发送、Token 生命周期、凭据存储和注册约束不完整 | 中等，安全闭环不足 |
| 角色权限 | 全局 `is_superuser`；Workspace owner/admin/member/viewer；YAML 权限矩阵；默认拒绝 | 权限检查分散在 Service；拒绝审计未统一；跨资源语义可能漂移 | 中上，执行一致性不足 |
| Workspace | 个人 Workspace、成员唯一约束、最后 owner 保护、软删除 | 删除后权限残留风险、`owner_id` 漂移、手机号成员响应类型冲突、前端管理面缺失 | 中等，存在高风险边界 |
| 审计 | actor、Workspace、资源、结果、IP、UA、request ID、metadata；独立写事务 | 事件覆盖不完整；无 outbox/重试告警、留存、脱敏和防篡改策略 | 中等，偏业务日志而非合规账本 |
| Credits | 账户、交易流水、UsageRecord；余额约束、行锁、原子扣减和幂等 | 用户级而非 Workspace 级；双配额账本；缺统一审计；过期扫描会持续扩张 | 中等，账务基础较好 |
| Feature Flags | GrowthBook、本地评估、缓存、熔断、fallback；系统级与用户级输出 | 注册表分散；敏感默认值 fail-open；后端执行与 UI 展示不一致；无生命周期治理 | 中等，适合灰度但不适合作为授权 |

### 3.2 登录与身份生命周期

当前 [`auth_api.py`](../../backend/api/v1/endpoint/auth_api.py) 暴露公开配置、注册、密码登录、SMS 发送/登录和 Google URL/callback。密码使用 [`security.py`](../../backend/core/security.py) 中 `PasswordHash.recommended()`，JWT 只包含 `sub`、`iat` 和 `exp`，鉴权依赖每次重新加载用户并校验 `is_active`。

已确认优势：

- 注册、密码登录、SMS 发送/登录和 Google callback 均有独立限流配置。
- SMS 验证通过 Redis Lua 实现单次消费、失败计数和锁定；Google ID Token 使用官方校验器验证签名、audience、issuer 和过期时间。
- 首次 SMS/Google 登录可创建用户和个人 Workspace；公开注册和 closed beta 可由系统 flag 门控。

已确认缺口：

- [`google_oauth_service.py`](../../backend/services/google_oauth_service.py) 生成授权 URL 时没有 `state`、PKCE 或 `nonce`；redirect allowlist 为空时直接接受任意 URI。
- Google claims 只返回 `sub/email/name`，账号按 email 自动关联前没有显式要求 `email_verified`。
- [`sms_service.py`](../../backend/services/sms_service.py) 的非 mock 分支仍是 TODO，当前不能视为生产可用短信登录。
- [`auth-store.ts`](../../frontend/apps/admin/src/stores/auth-store.ts) 明确把 JWT 持久化到 localStorage；后端无 refresh、撤销、`jti` 或 token version，前端声明的 `/auth/refresh` 也没有对应后端 endpoint。
- `enable-password-login` 只控制 [`AuthModal.tsx`](../../frontend/apps/admin/src/pages/Auth/AuthModal.tsx) 展示，密码登录 endpoint 并未据此拒绝请求。
- [`UserCreate`](../../backend/models/schemas/user_schema.py) 允许不提供密码，公开注册可能产生没有可用认证方式的账号。

### 3.3 角色权限与 Workspace

[`permissions.yaml`](../../configs/access/permissions.yaml) 定义 owner/admin/member/viewer 与 workspace、role、file、chat、audit 权限；owner 使用通配符，缺 Workspace 或缺角色默认拒绝，superuser 可配置绕过。策略由后端配置模型校验，并在应用启动期加载，配置错误能够 fail fast。

Workspace 服务保护最后一个 owner，并限制普通角色管理 owner。数据层通过 [`SoftDeleteMixin`](../../backend/models/orm/base.py) 对 ORM SELECT 自动附加 `deleted_at IS NULL`。

主要风险：

1. [`AccessRepository.get_workspace_role()`](../../backend/repositories/access_repo.py) 只查询 `UserWorkspaceRole`，不 join `Workspace`；成员表本身不带软删除字段。
2. [`KnowledgeService._ensure_kb_access()`](../../backend/services/knowledge_service.py) 对 Workspace KB 只按 `workspace_id` 调用权限服务。
3. 因此，Workspace 软删除后，历史角色可能继续使知识库或聊天资源通过授权。这是静态推断，不应在缺少真实数据库测试时直接宣称已复现越权。

其他一致性缺口：

- 新增或调整 owner 角色只更新成员表，不同步 `Workspace.owner_id`，对外 owner 元数据可能过期。
- `User.email` 可为空，但 [`WorkspaceMemberResponse`](../../backend/models/schemas/workspace_schema.py) 把 `email` 声明为必填 `str`，手机号用户可能触发响应校验错误。
- 前端当前没有完整的 Workspace 与成员角色管理面；后端治理能力主要依赖 API。

### 3.4 审计

[`AuditEvent`](../../backend/models/orm/access.py) 保存 actor、Workspace、action、resource、outcome、IP、UA、request ID 和 JSON metadata。 [`AuditService`](../../backend/services/audit_service.py) 默认使用独立 UoW 写入，审计失败只记录日志，不阻断主业务，适合可用性优先的业务审计。

当前事件覆盖登录、用户、Workspace、文件和聊天的部分关键写路径，但仍有明显空白：

- `AUTH_SMS_CODE_SENT` 与 `PERMISSION_DENIED` 已定义，却没有形成统一调用路径。
- SMS/Google 失败、公开注册、Credits checkin/spend/expire/adjust 未形成完整 AuditEvent。
- 独立写失败没有重试、指标或告警；可用性优先不等于满足合规不可丢失要求。
- 未发现留存、脱敏、导出/SIEM、完整性哈希或防篡改存储策略；异常字符串写入 metadata 还可能携带敏感信息。

### 3.5 Credits

[`CreditAccount`、`CreditTransaction` 和 `UsageRecord`](../../backend/models/orm/credits.py) 形成余额、流水和实际模型用量三层记录。Service 使用行锁、条件更新、savepoint 和消息级幂等键，数据库还有 `balance >= 0` 与唯一幂等索引，具备较好的并发与重复消费基础。

当前治理缺口：

- Credits 绑定 `user_id`，没有 Workspace/租户维度；未来若支持团队预算，需要先明确归属和授权模型。
- `User.max_tokens/used_tokens` 与 Credits 并存，消费算法可能同时扣两类额度，形成双账本和解释成本。
- `CreditTransaction.source` 是自由字符串，金额方向、来源和到期字段之间没有数据库一致性约束。
- Credits 流水未进入统一 AuditEvent，账务流水与治理审计无法按 request ID/actor 完整关联。
- [`list_accounts_needing_expiration()`](../../backend/repositories/credit_repo.py) 会持续枚举所有历史过期签到账户，没有“已处理”谓词或稳定 cursor；随着历史增长，批处理扫描成本会单调增加。

### 3.6 Feature Flags

[`FeatureFlagService`](../../backend/services/feature_flag_service.py) 从 GrowthBook CDN 拉取配置，使用 30 秒进程内缓存、3 秒请求超时、熔断和 fallback。系统级 flags 通过 `/auth/config` 暴露，用户级 flags 通过用户接口返回；前端只使用统一 Hook/Gate 消费结果，worker 任务会接收 Web 侧计算后的快照。

主要问题：

- flag 名称、默认值和说明分散在 Service、seed 脚本、YAML 与前端消费者，没有单一类型化注册表。
- 代码注册表不表达 owner、创建原因、到期日和下线条件，也没有 flag 变更审计。
- 冷启动无法访问 GrowthBook 时，`enable-public-registration` fallback 为 `true`，敏感注册控制会 fail-open。
- 缓存按 Web 进程独立存在，多 worker 在 30 秒窗口内可能观察到不同配置。
- `enable-password-login` 与 `enable-credits` 主要控制 UI，不应被理解为后端授权或计费禁用机制。

## 4. 测试覆盖映射

### 4.1 当前测试资产

后端统计以 `test_*.py` 中测试函数为口径；前端 Vitest 统计直接 `it()`/`test()` 调用，不展开参数化；Playwright 统计直接 `test()`。

| 技术栈 / 层级 | 文件或用例数 | 典型环境 |
| --- | --- | --- |
| 后端测试文件 | 125 个文件 | `tests/` 全层级 |
| 后端 unit | 911 个测试函数 | mock/fake repository、service、纯函数 |
| 后端 component | 38 个测试函数 | ASGI + dependency override/fake 依赖 |
| 后端 integration | 4 个测试函数 | PostgreSQL/Redis/TaskIQ 连通性与 SMS Lua |
| 后端 smoke | 8 个测试函数 | 运行中的 Docker/API 栈 |
| 后端 performance | 1 个 pytest 测试 | 默认排除，另有 Locust 工具 |
| 前端 Vitest | 37 个文件、约 298 个直接用例 | jsdom、MSW、模块 mock |
| 前端 Playwright mock | 11 个用例 | 浏览器 + route mock |
| 前端 Playwright smoke | 4 个用例 | 浏览器 + 真实 API/DB/Redis/worker |

### 4.2 身份治理域覆盖

| 领域 | 已有覆盖 | 关键缺口 |
| --- | --- | --- |
| 登录 | JWT、密码哈希、鉴权依赖、SMS Lua、Google token wrapper、用户自动创建；smoke 覆盖密码登录 | Auth Router 组件覆盖很薄；无 OAuth state/关联全链路、真实 SMS、Token 撤销、用户切换缓存隔离 |
| RBAC/Workspace | PermissionService、WorkspaceService 单测；smoke 有基本允许/拒绝路径 | 无 Workspace API 组件测试、真实 DB RBAC、软删除后访问、owner 元数据和手机号成员响应测试 |
| 审计 | Service、repository 查询和 API 权限单测 | 无真实独立事务失败、统一 denied 事件、敏感 metadata、留存或不可丢失语义测试 |
| Credits | Service/API 覆盖幂等、余额、checkin 和过期分支；前端 smoke 覆盖单用户 checkin/查询 | 无真实 PostgreSQL 并发扣费、重复消息恢复、批量过期和跨 Workspace 预算测试 |
| Feature Flags | backend fallback/熔断，frontend Hook/Gate/AuthModal | 无注册表/seed/YAML/消费者契约、冷启动敏感默认值、后端 flag 执行测试 |

代表性测试入口：

- 登录：[`test_auth_api.py`](../../tests/unit/api/test_auth_api.py)、[`test_auth_deps.py`](../../tests/unit/api/test_auth_deps.py)、[`test_google_oauth_service.py`](../../tests/unit/services/test_google_oauth_service.py)、[`test_sms_service_redis.py`](../../tests/integration/test_sms_service_redis.py)。
- 权限与 Workspace：[`test_permission_service.py`](../../tests/unit/services/test_permission_service.py)、[`test_workspace_service.py`](../../tests/unit/services/test_workspace_service.py)、[`test_core_api_flow_smoke.py`](../../tests/smoke/test_core_api_flow_smoke.py)。
- 审计与 Credits：[`test_audit_service.py`](../../tests/unit/services/test_audit_service.py)、[`test_credit_service.py`](../../tests/unit/services/test_credit_service.py)、[`real-credits.spec.ts`](../../frontend/apps/admin/e2e/tests/smoke/real-credits.spec.ts)。
- Flags：[`test_feature_flag_service.py`](../../tests/unit/services/test_feature_flag_service.py)、[`AuthModal.test.tsx`](../../frontend/apps/admin/src/pages/Auth/AuthModal.test.tsx)。

### 4.3 Mock 与真实环境比例

按层级做粗略计数：

- 后端隔离层为 unit + component，即 `911 + 38 = 949`；real-ish 层为 integration + smoke，即 `4 + 8 = 12`。排除 performance 后约为 **98.8% : 1.2%**。
- 前端隔离层为 Vitest + mock E2E，即 `298 + 11 = 309`；real-backend smoke 为 4。约为 **98.7% : 1.3%**。

该比例不能直接解释为“99% 测试无价值”。unit/component 对分支和失败语义很重要，真实 smoke 也覆盖了高价值主链路。真正的问题是 real-ish 层业务宽度太窄：后端 integration 主要证明服务连通，真实 DB 下的权限、软删除、Credits 并发和审计一致性仍没有证据；Docker 与前端 smoke 也统一使用 mock LLM/Embedding，没有覆盖真实 SMS/Google。

## 5. CI 门禁与代码质量

### 5.1 当前门禁矩阵

| Workflow | 当前覆盖 | 判断 |
| --- | --- | --- |
| [`static-ci.yml`](../../.github/workflows/static-ci.yml) | backend lint/format/typecheck/boundaries/markers/Alembic/standards/unit/component；frontend lint/typecheck/coverage/build/bundle/Pages build | 静态门禁完整，是当前质量主力 |
| [`pr-gate-ci.yml`](../../.github/workflows/pr-gate-ci.yml) | PostgreSQL/Redis + `make qa-test-ci`；Playwright mock E2E | 声称补 integration，但实际重新收集大部分后端 suite，存在重复执行 |
| [`frontend-e2e-smoke-ci.yml`](../../.github/workflows/frontend-e2e-smoke-ci.yml) | migration、seed、API、worker、真实 PostgreSQL/Redis、4 个浏览器 smoke | 真实契约门禁价值高，但场景较少且 AI provider 为 mock |
| [`smoke-ci.yml`](../../.github/workflows/smoke-ci.yml) | Docker 构建、启动、严格 HTTP smoke | 是 required check，但 PR paths 未覆盖普通业务源码 |
| [`security-ci.yml`](../../.github/workflows/security-ci.yml) | Python/npm dependency audit、backend/frontend image scan | 长期失败且不 required，当前没有形成有效门禁 |
| [`guard-branch-protection.yml`](../../.github/workflows/guard-branch-protection.yml) | 定时检查 required checks | 读取 classic protection，不能识别当前 Ruleset，持续误报 |

### 5.2 后端覆盖率门禁未生效

[`pyproject.toml`](../../pyproject.toml) 配置 `coverage source = backend` 和 `fail_under = 75`，并安装 `pytest-cov`；但 `qa-test-unit`、`qa-test-component`、`qa-test-ci` 及 workflows 都没有传入 `--cov`。因此：

- CI 不会计算后端 coverage；
- 75% floor 不会触发失败；
- 没有可下载的后端 coverage artifact 或趋势；
- 当前配置容易给维护者造成“已有覆盖率门禁”的错误安全感。

前端则是真门禁：[`vitest.config.ts`](../../frontend/apps/admin/vitest.config.ts) 把全量 `src` 纳入分母，阈值为 statements 40%、branches 30%、functions 35%、lines 40%，Static CI 直接执行 coverage 并上传 artifact。

### 5.3 Ruleset 与 Workflow 触发冲突

2026-07-17 的只读查询确认：

- default branch 上有 active Ruleset `Rules`（ID `17659301`），要求 PR、禁止删除和 non-fast-forward。
- required checks 为 `Backend static`、`Frontend static`、`PR gate`、`Frontend e2e smoke (real backend)`、`Docker smoke`。
- `strict_required_status_checks_policy=false`，分支不要求在合并前严格更新到最新基线。
- classic branch protection API 返回 404；保护来自 Ruleset，而不是 classic protection。

[`smoke-ci.yml`](../../.github/workflows/smoke-ci.yml) 的 PR paths 只包含 Docker/compose、依赖锁、镜像、smoke 脚本/测试和 workflow 自身，不包含一般 `backend/**`、前端业务源码、迁移或权限配置。Ruleset 却对所有默认分支 PR 要求 `Docker smoke`，因此普通代码 PR 可能一直等待一个不会创建的 check。

[`guard-branch-protection.yml`](../../.github/workflows/guard-branch-protection.yml) 仍读取 classic endpoint，所以会把“Ruleset 正常、classic 不存在”误判为完全没有 required checks。

### 5.4 Actions 运行快照

最近 100 次运行样本：

| Workflow | 样本结果 |
| --- | --- |
| Static CI | 16/16 success |
| PR Gate CI | 16/16 success |
| Frontend E2E Smoke CI | 16/16 success |
| Smoke CI | 16/16 success |
| Security CI | 20/20 failure |
| Guard Branch Protection | 4/4 failure |

这不是正式的 flake rate：样本包含大量 schedule/Dependabot，且活跃业务 PR 数有限。但它足以证明 Security 和 Guard 已经处于持续红灯状态。最新 Security run 为 [29227258724](https://github.com/Turing222/dewflow/actions/runs/29227258724)：Backend image scan 成功，Python dependency、Frontend dependency 与 Frontend image 三个 job 失败。当前 lock 仍固定 `pydantic-ai-slim 1.66.0`、`pydantic-settings 2.12.0` 和 `form-data 4.0.5`，应作为依赖扫描首批复核对象，但具体 advisory 仍以重新运行扫描后的报告为准。

## 6. 慢测与执行效率

当前“慢测”不是迫切性能事故。2026-07-13 最近一次成功运行中，Static、PR Gate、Smoke 和 Frontend E2E workflow 总耗时约 1.5–2.1 分钟，仍在合理 PR 反馈窗口内。

但慢测治理本身不完整：

- pytest 固定 `-n 1`，Vitest `fileParallelism=false`；串行是当前稳定性选择，不应在缺少隔离证明时直接打开并发。
- CI 没有 pytest `--durations`、Vitest slow test 报告、JUnit 历史或时间预算，无法识别单测逐步变慢。
- Static CI 已运行 unit/component，PR Gate 的 `make qa-test-ci` 又收集整个符合 marker 的测试树；integration 只有 4 个测试，重复执行的收益偏低。
- PR Gate 提供 PostgreSQL/Redis，但没有先运行 Alembic migration，现有 integration 又以连通性为主，基础设施成本没有转化为足够的业务一致性证据。
- performance suite 默认排除，当前只有 1 个 pytest performance test 与本地 Locust 工具，没有 schedule regression gate。

优化顺序应是先输出时长和消除重复，再评估并发；不要为了缩短一两分钟牺牲数据库隔离或 React 19 teardown 稳定性。

## 7. 风险登记

| ID | 优先级 | 风险 | 目标证据 |
| --- | --- | --- | --- |
| R1 | P0 | Workspace 软删除后残留角色可能继续授权下游资源 | 真实 PostgreSQL 回归复现或证伪；删除后 KB/chat 全部拒绝 |
| R2 | P0 | OAuth 会话未绑定、redirect fail-open、SMS 生产路径未完成、Token 无撤销 | OAuth 攻击路径测试；生产配置 fail-closed；Token 生命周期验收 |
| R3 | P0 | required `Docker smoke` 与 paths 过滤冲突 | 任意普通业务 PR 都产生并完成同名 check |
| R4 | P0 | 后端 75% coverage floor 未执行 | CI 生成 coverage report 并由 floor 阻断回归 |
| R5 | P0 | Security CI 持续失败且不阻断 | 生产依赖/镜像扫描恢复绿色，再纳入 required 或明确例外策略 |
| R6 | P1 | 审计事件选择性覆盖，失败可静默丢失 | 事件矩阵、失败指标/告警、留存/脱敏与重试策略 |
| R7 | P1 | Credits 双账本、用户级归属和过期扫描扩张 | 产品归属决策、约束化流水、真实并发与批处理测试 |
| R8 | P1 | 约 99:1 的隔离/真实环境分布使关键数据库语义缺证据 | RBAC、软删除、Credits、审计真实 DB 测试集 |
| R9 | P2 | Feature flag 注册表、owner、到期和执行语义分散 | 单一注册表与 seed/消费者契约测试 |
| R10 | P2 | 无慢测趋势且 PR Gate 重复执行 | durations/JUnit 趋势、按层级精确执行、明确时间预算 |

## 8. 推荐落地顺序

### 8.1 P0-A：先修复门禁可信度

1. 让 `Docker smoke` 对所有需要它的 PR 都创建 check；可选择移除 paths 过滤，或将 Ruleset required check 改成始终运行的轻量聚合 job。
2. Guard 改读 Rulesets API，同时保留 classic protection 兼容分支；校验 required context、enforcement 和 default branch 条件。
3. 后端测试增加 `--cov=backend`、机器可读报告和 `--cov-fail-under=75`；先记录真实基线，若低于 75，应显式调整过渡 floor，而不是静默不执行。
4. 修复当前生产依赖与镜像告警，使 Security CI 先稳定为绿色；随后决定哪些 job 必须 required，哪些允许带到期日的风险豁免。

### 8.2 P0-B：关闭身份与 Workspace 高风险边界

1. 角色查询 join 活跃 Workspace，或在 PermissionService 统一校验 Workspace 存在且未删除；软删除同时撤销/冻结成员和活跃资源入口。
2. 增加真实 PostgreSQL 测试：删除 Workspace 后，workspace API、KB、文件、chat session、audit 查询全部拒绝。
3. OAuth 增加服务端绑定的 `state`，采用 PKCE，生产环境 redirect allowlist 为空时启动失败；账号按 email 关联前显式要求 verified email。
4. 后端真正执行 password-login flag；真实 SMS provider 未接通前，生产配置不得启用 SMS 登录。
5. 明确 access/refresh token、撤销和注销模型，并逐步把浏览器凭据迁移到安全 cookie；至少保证 401 和用户切换会清理全部用户绑定缓存。

### 8.3 P1：用风险驱动的真实测试补齐治理证据

- 为 auth、workspace、audit、credits 增加 ASGI component tests，覆盖 endpoint 序列化、依赖装配和审计上下文。
- 把 integration 从“服务能 ping”扩展到 RBAC、软删除、唯一约束、Credits 并发/幂等和 audit 独立事务。
- 保留少量高价值 E2E，不追求把所有 unit 场景搬到浏览器；为 SMS/Google 使用供应商 sandbox 或合同测试，而不是生产凭据。
- 增加 Feature Flag 契约测试，校验注册表、seed 配置、后端输出和前端消费者没有漂移。

### 8.4 P1/P2：补齐治理与效率

- 审计建立 action × outcome × actor × workspace × retention 矩阵；写入失败暴露 metric/alert，需要不可丢失的事件使用 outbox。
- 明确 Credits 是个人权益还是 Workspace 预算，统一 Credits 与 Token 配额的产品解释和账务事实源。
- 为 flag 增加 owner、scope、fallback、consumer、created_at、expires_at 和 removal plan；flag 不能替代权限检查。
- pytest 输出 `--durations=20` 和 JUnit；按 marker 让 PR Gate 只执行 integration，消除与 Static CI 的大面积重复后，再基于趋势讨论并发。

## 9. 证据索引

### 9.1 身份与治理

- 登录入口与门控：[`auth_api.py`](../../backend/api/v1/endpoint/auth_api.py)、[`security.py`](../../backend/core/security.py)、[`google_oauth_service.py`](../../backend/services/google_oauth_service.py)、[`sms_service.py`](../../backend/services/sms_service.py)。
- 权限与 Workspace：[`permissions.yaml`](../../configs/access/permissions.yaml)、[`access_repo.py`](../../backend/repositories/access_repo.py)、[`workspace_service.py`](../../backend/services/workspace_service.py)、[`base.py`](../../backend/models/orm/base.py)。
- 审计、Credits 与 Flags：[`audit_service.py`](../../backend/services/audit_service.py)、[`credits.py`](../../backend/models/orm/credits.py)、[`credit_service.py`](../../backend/services/credit_service.py)、[`feature_flag_service.py`](../../backend/services/feature_flag_service.py)。
- 前端身份与 flag 消费：[`auth-store.ts`](../../frontend/apps/admin/src/stores/auth-store.ts)、[`AuthContext.tsx`](../../frontend/apps/admin/src/context/AuthContext.tsx)、[`useFeatureFlag.ts`](../../frontend/apps/admin/src/context/useFeatureFlag.ts)。

### 9.2 测试与 CI

- 测试分层约定：[`tests/README.md`](../../tests/README.md)、[`tests/CONVENTIONS.md`](../../tests/CONVENTIONS.md)、[`testing.md`](../../frontend/docs/standards/testing.md)。
- 运行配置：[`pyproject.toml`](../../pyproject.toml)、[`vitest.config.ts`](../../frontend/apps/admin/vitest.config.ts)、[`playwright.config.ts`](../../frontend/apps/admin/e2e/playwright.config.ts)、[`Makefile`](../../Makefile)。
- CI 事实源：[`static-ci.yml`](../../.github/workflows/static-ci.yml)、[`pr-gate-ci.yml`](../../.github/workflows/pr-gate-ci.yml)、[`frontend-e2e-smoke-ci.yml`](../../.github/workflows/frontend-e2e-smoke-ci.yml)、[`smoke-ci.yml`](../../.github/workflows/smoke-ci.yml)、[`security-ci.yml`](../../.github/workflows/security-ci.yml)。
- 长期流程文档：[`ci-test-matrix.md`](../workflows/ci-test-matrix.md)、[`feature-flags.md`](../../frontend/docs/standards/feature-flags.md)。

### 9.3 GitHub 快照复核命令

```bash
gh api repos/Turing222/dewflow/rulesets/17659301
gh api repos/Turing222/dewflow/branches/main/protection/required_status_checks
gh run list --repo Turing222/dewflow --limit 100 --json workflowName,conclusion,createdAt
```

## 10. 最终结论

身份治理域已经具备值得保留的结构：登录方式分层、配置化 RBAC、Workspace 隔离、独立审计、幂等 Credits 流水和集中 Feature Flag 评估都不是临时拼接。当前风险来自这些结构之间的缝隙，以及门禁“声明存在但未真正执行”。

近期最有价值的工作是先让 CI/Ruleset/coverage/security 结果可信，再关闭 Workspace 删除授权和 OAuth/Token 生命周期边界，同时用少量真实 PostgreSQL 测试证明关键治理语义。继续增加大量 mock 单测或盲目并发提速，都不能替代这一步。
