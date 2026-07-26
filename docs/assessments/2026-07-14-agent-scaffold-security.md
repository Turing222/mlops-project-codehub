# 双 Agent 脚手架安全与治理复核

> 日期：2026-07-14
> 范围：`CLAUDE.md`、`AGENTS.md`、`.codex/skills/`、Claude rules、Serena MCP、agent 侧凭据与本地 worktree secret 管理
> 性质：时点评估；整合两份独立扫描报告并做脱敏复核，只新增本文与中央索引，不修改运行配置或凭据
> 证据基线：分支 `chore/deps-batch-patch`、提交 `099ec68`、Claude Code `2.1.207`、Codex CLI `0.139.0`
> 状态：冻结；用户级配置与凭据结论仅代表本机快照，后续现行约定以仓库配置和宿主配置为准

## 1. 结论速览

Dewflow 当前是一套成熟的双客户端 agent 脚手架：8 个共享 skills、Claude Code / Codex 双入口路由、服务端锁定只读的 Serena，以及进入 CI 的 skill / docs 契约校验，已经形成较完整的治理闭环。

当前主要风险不在应用运行时 secret 或 Serena 本身，而在**用户级 agent 凭据与 Claude Code 本机权限组合**：本机 Claude 认证 token 存在于 `0644` 文件；Context7 key 有三处明文副本；本机启用了 `bypassPermissions` 与“自动启用所有项目 MCP”组合，同时仓库还没有针对真实 secret 路径的 hook 防线。

建议顺序：

1. 若此前扫描确实读取过 Claude token，立即轮换；无论是否读取过，都将凭据文件收紧为 `0600` 并迁出常规 settings。
2. 将 Context7 三处明文收敛到一个经当前客户端验证的环境变量或 secret helper 来源。
3. 删除本机 `enableAllProjectMcpServers`，只保留显式 Serena 白名单。
4. 增加范围精确、允许模板文件的 secret 访问 hook；把它视为 agent 治理措施，不视为 OS 安全边界。
5. 再处理 worktree secret 单一来源、PostToolUse 审计接线和 rules 蒸馏同步等维护性问题。

## 2. 复核方法与证据边界

本报告以两份候选评估文本为输入，但不直接继承其中的数量、路径或优先级；争议项以当前文件、当前客户端版本和脱敏检查结果裁决。

| 证据类型 | 检查方式 | 边界 |
| --- | --- | --- |
| 仓库配置 | 读取已跟踪配置、脚本、skills、文档与 Git 元数据 | 不修改任何运行文件 |
| 用户级配置 | 只检查文件 mode、字段名、是否非空及副本是否相等 | 不读取、不记录、不回显 secret 值 |
| 本地 secret | 只统计目录类型、文件 mode 和非空文件数量 | 不读取文件名对应的值 |
| 机械校验 | `make qa-skill-check`、`make qa-docs` | Serena 真实 stdio smoke 未在本次重复执行 |

用户级 findings 是本机风险，不应自动解释为仓库对所有贡献者的默认行为。特别是 `.claude/settings.local.json` 由用户级 Git ignore 排除，不是团队共享配置；但它会影响本机如何信任仓库中的 `.mcp.json`。

## 3. 当前架构全景

| 层 | Claude Code | Codex | 事实源或关系 |
| --- | --- | --- | --- |
| 路由入口 | [`CLAUDE.md`](../../CLAUDE.md) | [`AGENTS.md`](../../AGENTS.md) | 共享核心约束，保留少量客户端差异 |
| 常驻蒸馏规则 | `.claude/rules/` 4 个文件 | 不读取此层 | 蒸馏自 project references 与 frontend standards |
| 完整项目规则 | 按需读取 | 按需读取 | [`.codex/skills/project/references/`](../../.codex/skills/project/references/task-mode.md) 9 个 references |
| 任务模式 | 7 个任务 skills | 7 个任务 skills | 加上 `project` 共 8 个 skill 目录 |
| Serena 入口 | [`.mcp.json`](../../.mcp.json) | [`.codex/config.toml`](../../.codex/config.toml) | 共用 [`serena-mcp.sh`](../../scripts/dev/serena-mcp.sh) |
| Serena 策略 | 客户端 allow / deny | 客户端 enabled tools | [`.serena/project.yml`](../../.serena/project.yml) 是服务端事实源 |
| 契约校验 | 同一套 Make targets | 同一套 Make targets | [`check_skills.py`](../../scripts/qa/check_skills.py) 与 [`check_docs.py`](../../scripts/qa/check_docs.py) |

“8 个 skills”与“7 个任务 skills”是统计口径不同，不是事实冲突。`CLAUDE.md` 与 `AGENTS.md` 也不应追求逐字镜像：例如删除数据前的警告在 Codex 入口中常驻，而 Claude Code 通过 always-on `editing.md` 获得同一约束。

## 4. 已确认的优势

### 4.1 Skills 与双入口路由

- `SKILL.md` 保持路由和核心流程，细节下沉到 `references/`，渐进式披露清晰。
- `review`、`debug` 的多 pass / 证据优先协议成熟，且 fix、review、production incident 的模式边界已集中到 `task-mode.md`。
- 两个入口都索引相同 8 个 skills；`check_skills.py` 会校验结构、链接、Make target 和路由清单。
- Claude rules 与共享 references 的少量差异有客户端原因，不宜机械要求全文相同。

### 4.2 Serena 只读防线

当前活跃集是 1 个 bootstrap 工具 `initial_instructions` 加 5 个导航/诊断工具，共 6 个，而不是 5 个总工具：

- [`.serena/project.yml`](../../.serena/project.yml) 使用 `read_only: true` 和 6 项 `fixed_tools`，构成服务端硬约束。
- Codex `enabled_tools` 与 Claude `allow` 镜像该集合；`check_skills.py` 会机械比较三处配置。
- Claude `deny` 当前有 14 个写入或状态变更工具，是 `fixed_tools` 被误删时的防御性兜底；其意图已写入 [`task-mode.md`](../../.codex/skills/project/references/task-mode.md)。
- 启动器使用 `--mode no-memories` 并关闭 dashboard，避免额外记忆和管理面。

### 4.3 应用 secret 与 QA

- [`secret_env.py`](../../backend/core/secret_env.py) 只允许白名单中的 24 个 secret 通过 `FOO_FILE` 注入。
- [`.gitignore`](../../.gitignore) 默认忽略 `secrets/{smoke,ec2,local-prod}/` 真值，只放行 README 与 `.gitkeep`。
- [`secrets-and-flags.md`](../../.codex/skills/project/references/secrets-and-flags.md) 给出新增 secret 的完整接线和测试清单。
- `make qa-standards-fast` 已进入 `static-ci`，同时运行 skill、docs 与快速 standards 校验；`qa-serena-smoke` 保留为需要本机 LSP 依赖的 opt-in 检查。

## 5. 已确认问题与风险

### 5.1 P0：Claude 用户级认证 token 权限过宽

本机 `~/.claude/settings.json` 当前 mode 为 `0644`，其中存在非空 `ANTHROPIC_AUTH_TOKEN`，且未配置 `apiKeyHelper`。这会让同机其他用户读取该文件；改成 `0600` 可以收紧跨用户读取，但不能阻止同一用户权限下的进程。

一份输入报告自述曾直接 `cat` 此文件。如果该陈述属实，token 已进入当次模型和中转链路，应立即轮换。安全扫描本应只检查权限、字段与非空状态，本报告没有读取该值。

### 5.2 P1：Context7 key 有三处明文副本

脱敏结构检查确认，同一 Context7 key 当前存在于：

1. `~/.codex/config.toml` 的 `headers.CONTEXT7_API_KEY`；
2. 同一文件的 `http_headers.CONTEXT7_API_KEY`；
3. `~/.claude.json` 的 `mcpServers.context7.headers.CONTEXT7_API_KEY`。

三份当前相等。两个用户级配置文件 mode 均为 `0600`，因此首要问题是明文、重复和轮换漂移，而不是跨用户可读。应先确认各客户端实际消费的字段，再迁移到单一外部来源；不能把 key 搬进 Plugin 或仓库配置。

### 5.3 P1：本机 Claude 权限与项目 MCP 自动启用形成组合面

本机 `.claude/settings.local.json` 设置了 `defaultMode: bypassPermissions`、`enableAllProjectMcpServers: true`，同时显式列出 `enabledMcpjsonServers: ["serena"]`；用户级 settings 还设置了 `skipDangerousModePermissionPrompt: true`。

当前 `.mcp.json` 只有只读 Serena，因此没有立即越权。但未来 PR 若加入新 MCP，`enableAllProjectMcpServers` 会扩大自动启用面。该风险属于“本机信任策略 × 已跟踪项目配置”的组合，而不是当前 Serena 的缺陷。

### 5.4 P1：真实 secret 路径没有 agent 侧定向拦截

已跟踪的 `.claude/settings.json` 当前只有 Serena allow / deny，没有 hooks，也没有针对 `secrets/**` 或真实 `.env` 文件的规则。本机 Claude Code `2.1.207` 明确保留 explicit deny 作为 `bypassPermissions` 的例外，PreToolUse hook 也可以在工具执行前拒绝调用。

建议同时采用显式 deny 与 PreToolUse，但路径规则必须允许 `.env*.template`、README 和 `.gitkeep` 等可公开文件。Bash 命令可通过脚本、软链或间接解释器绕过简单字符串匹配，因此 hook 只能降低 agent 误读和常见 prompt injection 风险，不能替代进程隔离、最小权限或外部 secret manager。

### 5.5 P2：已有 PostToolUse 审计脚本未接线

[`post_edit_audit_hook.py`](../../scripts/qa/post_edit_audit_hook.py) 已实现 Claude PostToolUse 适配器：从 stdin 解析编辑文件，对路径运行快速 standards audit，并在违规时返回 block / additional context。仓库中除脚本自身外没有引用，当前不会执行。

Makefile 已保留 `qa-claude-fast` 别名并注明用于 Claude hook wiring，说明脚本与 target 的设计意图一致。接线前仍应验证 matcher、单次耗时、失败返回格式以及 PostToolUse 只能阻止继续执行、不能撤销已发生编辑的语义。

### 5.6 P2：本地 secret mode 与 worktree 副本不一致

当前 `secrets/local-prod/` 目录 mode 为 `0700`，其中 26 个普通文件均为 `0644`；目录权限阻止其他用户穿透，但文件 mode 与 `smoke` / `ec2` 中真实 secret 使用 `0600` 的做法不一致。

三个 worktree 都存在各自的 `secrets/` 与 `.env.smoke`，且各 `secrets/` 目录均包含非空文件。副本不会被 Git 跟踪，但会增加轮换遗漏和暴露面积。优先考虑让现有 `SMOKE_FOO_FILE` / `FOO_FILE` 指向经过权限控制的共享来源；只有在 Docker build context、脚本相对路径和备份行为验证通过后，才考虑软链。

### 5.7 P2：Claude 蒸馏 rules 的语义同步仍靠人工

`.claude/rules/` 的 4 个文件声明蒸馏自 project references 或 frontend standards，但 `check_skills.py` 只校验结构、链接和显式清单，不比较两层语义。当前没有发现明确冲突；风险在于后续只修改完整 reference 而忘记回看对应 rule。

更合适的治理是把“修改 reference 时回看对应 distilled rule”加入编辑约定，或只对少量可机械表达的不变量增加断言，而不是要求 Claude 与 Codex 的所有入口逐字镜像。

### 5.8 P3：Serena 静默降级是已接受的可观测性取舍

Codex 的 `required = false` 与 60 秒启动超时会在 Serena 不可用时回退文本搜索。该行为已在 `task-mode.md` 明确记录为 WSL / 冷启动友好的有意策略，因此不应再描述为未确认缺陷。

若任务依赖跨文件引用完整性或精确符号诊断，可以在最终回答中声明本次使用了文本回退；普通读取任务无需把它升级为阻塞错误。

### 5.9 P3：Plugin 提取硬编码仅在启动提取时处理

`.serena/project.yml` 仍绑定 Dewflow 的 TypeScript language server 路径和 Pyright 版本；`check_skills.py` 仍绑定仓库根目录、`.codex/skills` 与 Makefile。这些是当前 repo-local 设计的一部分，仅在实施 Serena / skill-governance Plugin 提取时才构成阻碍，不应进入近期安全整改主线。

## 6. 两份输入报告的争议项裁决

| 争议项 | 当前裁决 |
| --- | --- |
| 8 个 skills vs 7 个 skills | 8 个目录；其中 1 个 `project`、7 个任务 skills，两种说法口径不同 |
| Serena 5 个 vs 6 个工具 | 5 个导航/诊断工具，加 1 个 `initial_instructions`，总计 6 个 |
| Claude deny 9 项 vs 14 项 | 当前配置为 14 项；旧报告中的 9 已过时 |
| `bypassPermissions` 位于何处 | 位于未跟踪的 `.claude/settings.local.json`，不是已跟踪 `.claude/settings.json` |
| deny 缺少用途说明 | 配置文件本身没有说明，但 `task-mode.md` 已明确记录防御性兜底语义，不是当前缺口 |
| Tavily key 内嵌 URL | 当前脱敏结构检查未发现 query、长 secret path 或 header key；该结论未被当前状态支持 |
| `git add -A` hook 是最高优先级 | 只能防宽泛暂存，不能证明 commit / push 获得用户授权，应降为普通工作流护栏 |
| Serena 静默回退 | 是已记录的可用性选择；只在高精度任务中增加可见性提示 |

## 7. 推荐行动与验收条件

| 优先级 | 动作 | 作用域 | 最低验收条件 |
| --- | --- | --- | --- |
| P0 | 若 token 曾被读取则轮换；将 Claude 凭据文件改为 `0600`，迁移到 helper / secret store | 用户级 | settings 不再保存长期明文 token；Claude 登录与模型调用正常 |
| P1 | Context7 改为单一外部 secret 来源，移除三处明文副本 | 用户级 | Claude 与 Codex 均可调用；轮换只改一处；配置不回显 key |
| P1 | 删除 `enableAllProjectMcpServers`，保留显式 Serena 列表 | 本机项目设置 | 重启会话后仅 Serena 自动启用；新增未知 MCP 不会自动获信 |
| P1 | 增加精确的 secret deny + PreToolUse hook | 已跟踪 Claude 配置 / 脚本 | bypass 下真实 secret 被拒绝；template、README、`.gitkeep` 可读；Bash 间接读取有测试样例 |
| P2 | 将 `local-prod` 真值统一为 `0600`，减少 worktree 真值副本 | 用户级 / 本地运行 | compose、smoke 和轮换流程通过；每个 secret 只有明确主来源 |
| P2 | 接线并验证 `post_edit_audit_hook.py` | 已跟踪 Claude 配置 | Edit / Write 后只审计目标文件；失败提示可操作；耗时可接受 |
| P2 | 补充 distilled rules 同步约定 | 项目文档 | 修改 reference 的流程明确要求检查对应 `.claude/rules/` |
| P3 | 高精度任务声明 Serena 文本回退 | skill / 回答约定 | Serena 不可用时不阻塞；需要语义完整性的回答能识别降级 |
| 按需 | 参数化 Serena 与 skill validator | Plugin 提取工作项 | 仅在批准跨仓库提取后实施，并在非 Dewflow repo 验证 |

不建议把“禁止 `git add .` / `git add -A`”当作当前最高安全整改。它可以作为低成本工作流 hook，但应与 secret 防护分开，也不能被描述为“不自动提交”的机械证明。

## 8. 证据索引与复核结果

### 8.1 项目证据

- [`AGENTS.md`](../../AGENTS.md) 与 [`CLAUDE.md`](../../CLAUDE.md)：双客户端入口与 8 个 skills 路由。
- [`.serena/project.yml`](../../.serena/project.yml)：`read_only`、6 个 `fixed_tools`、LSP 绑定和 initial prompt。
- [`.codex/config.toml`](../../.codex/config.toml)、[`.mcp.json`](../../.mcp.json)、[`.claude/settings.json`](../../.claude/settings.json)：两个客户端的 Serena 接线与权限镜像。
- [`task-mode.md`](../../.codex/skills/project/references/task-mode.md)：Serena 三层权限语义和静默回退策略。
- [`check_skills.py`](../../scripts/qa/check_skills.py)：skill / route / Serena allowlist 契约校验。
- [`post_edit_audit_hook.py`](../../scripts/qa/post_edit_audit_hook.py)：未接线的 PostToolUse 审计适配器。
- [`secret_env.py`](../../backend/core/secret_env.py)、[`.gitignore`](../../.gitignore) 与 [`secrets-and-flags.md`](../../.codex/skills/project/references/secrets-and-flags.md)：应用 secret 白名单、忽略和接线规则。
- [`2026-06-12-skill-agent-mcp.md`](2026-06-12-skill-agent-mcp.md) 与 [`2026-07-10-codex-plugin-extraction.md`](2026-07-10-codex-plugin-extraction.md)：此前 skill / MCP 与 Plugin 提取时点快照。

### 8.2 用户级脱敏证据

- `~/.claude/settings.json`：mode、顶层字段、token 是否非空、是否存在 `apiKeyHelper`；未读取值。
- `~/.claude.json` 与 `~/.codex/config.toml`：Context7 表结构、header 字段名和副本相等性；未读取值。
- 三个 worktree 的 `secrets/`：目录类型、文件 mode 与非空文件数量；未读取值。
- Claude Code `2.1.207` 本机内置帮助：explicit deny 仍是 bypass 的例外，PreToolUse 可在执行前阻断。

### 8.3 机械校验

- `make qa-skill-check`：通过。
- `make qa-docs`：通过。

## 9. 最终结论

项目级骨架已经健康：skills 共享、入口清晰、Serena 服务端只读、契约进入 CI。近期不需要重构整个 agent 体系，也不需要因为 Serena 静默回退或入口存在有意差异而扩大改造。

最有价值的下一步是收紧用户级凭据与本机 Claude 信任面：先处理可能已暴露的认证 token，再统一 Context7 secret 来源、关闭项目 MCP 全自动启用，并用精确 hook 降低 agent 误读真实 secret 的风险。其余事项属于可维护性增强，应在不破坏双客户端单一技能源的前提下渐进实施。
