# Codex Plugin 提取评估

> 日期：2026-07-10
> 范围：项目级 `AGENTS.md`、`.codex/skills/`、Serena MCP、work-item 资产，以及用户级 `~/.codex/` 配置、skills、rules 和已安装插件
> 性质：时点评估；只新增本文并更新 `docs/README.md` 中央索引，不创建、安装或启用任何 Plugin
> 证据基线：分支 `chore/deps-batch-patch`、提交 `68aa847` 与文末证据索引
> 状态：冻结；后续 Plugin 实现与安装状态不回写本文

## 1. 结论速览

当前资产在技术上可以提取为 **4 组候选 Plugin**，但不应把所有 Codex 配置机械搬进 Plugin：

| 优先级 | 候选 Plugin | 当前来源 | 技术可行性 | 建议 |
| --- | --- | --- | --- | --- |
| A | `durable-work-items` | `task-plan` skill + `work-items/templates/` | 高 | 最适合先提取；跨仓库复用价值最高 |
| B | `serena-readonly-navigation` | Serena MCP 启动器、策略和只读工具集 | 中高 | 可提取，但必须先消除 Dewflow 路径和双客户端耦合 |
| B | `dewflow-engineering-workflows` | `project/read/write/edit/add-tests/review/debug` skills | 高 | 只适合 repo/team marketplace；不建议发布为通用公共插件 |
| C | `context7-docs` | 用户级 Context7 MCP | 中 | 仅在多人共享或需要统一启停时值得；单用户继续用 MCP 配置更轻 |

另外有一组可作为上述 Plugin 的配套能力：`scripts/qa/check_skills.py` 可改造成插件自检脚本或 hook，但当前硬编码项目路径，不宜直接打包。

**不应提取为 Plugin** 的内容包括：`AGENTS.md` 的仓库强约束、模型与 service tier、project trust、用户批准规则、OAuth/API key、活跃 work-item 状态、Claude Code 专用权限镜像。这些分别属于仓库指导、宿主配置、安全策略、凭据或运行状态，迁移会改变语义或扩大风险。

## 2. “可提取”的判定标准

本报告把“可提取”限定为同时满足以下条件，而不是“文件能复制进某个目录”：

1. **属于 Plugin 支持的能力面**：skills、MCP-backed app / connector、MCP server config、hooks、browser extension 或 scheduled-task template。
2. **存在安装/启停价值**：能力需要跨仓库、跨用户或按任务选择，而不是每次进入 Dewflow 都必须生效。
3. **可自包含**：引用、脚本、模板和运行依赖能随包移动，或者能通过稳定的宿主接口解析。
4. **不携带秘密与状态**：API key、OAuth token、用户授权、project trust、活跃任务状态不进入包。
5. **迁移后不破坏现有客户端**：Dewflow 当前由 Codex 与 Claude Code 共享 `.codex/skills/`；Codex Plugin 不能被假定为 Claude Code 的分发机制。

因此，本文区分三个概念：

- **打包可行**：格式上能放进 Plugin。
- **迁移可行**：删除原文件后，现有行为仍能保持。
- **值得提取**：分发、版本化和可选启停收益大于新增复杂度。

## 3. 官方依据：为什么可以这样做

OpenAI 当前文档给出的 Plugin 边界与本项目候选直接对应：

| 官方能力 | 对本项目的含义 |
| --- | --- |
| Plugin 可以包含一个或多个 skills、App、MCP server、hooks 等组件 | 现有 8 个 skills 与 Codex 侧 Serena / Context7 MCP 都属于可打包能力面；Claude 镜像不由 Plugin 消费 |
| 本地 skill 适合单 repo / 单人迭代；需要跨团队分发、绑定 connector/MCP 或发布稳定包时再做 Plugin | Dewflow 专属 rules 不必为了“新机制”强行迁移；`task-plan` 等跨仓库能力更适合提取 |
| Skill 可携带 `references/`、`scripts/`、`assets/`、`agents/openai.yaml` | 现有渐进披露 references、UI metadata 和 work-item templates 有对应承载位置 |
| Plugin 必须有 `.codex-plugin/plugin.json`，通过 repo 或 personal marketplace 分发 | 可分别建立项目级目录与个人目录，而不写入现有 `config.toml` 业务配置 |
| Connector / MCP 的认证独立发生；安装 Plugin 不等于把登录态打进包 | Context7 key、Figma/其他 OAuth 登录态必须留在安全授权层 |
| 安装后的 skills/tools 在新 chat/session 可用 | Plugin 启停会改变后续会话的能力清单和初始 skill metadata 上下文 |

官方来源：

- [Plugins：组成、安装、权限与移除](https://learn.chatgpt.com/docs/plugins)
- [Build plugins：适用场景、manifest、marketplace 与目录布局](https://learn.chatgpt.com/docs/build-plugins)
- [Build skills：skill 结构、渐进披露、作用域与 Plugin 分发](https://learn.chatgpt.com/docs/build-skills)

其中最关键的产品边界是：**仍在单个 repo 或个人工作流中快速迭代时优先保留 local skill；需要共享、稳定版本、MCP/connector 组合或生命周期 hook 时才升级成 Plugin**。因此本报告不会把“可打包”误写成“都应该迁移”。

本机 `codex-cli 0.139.0` 也已提供 `codex plugin add/list/remove` 与 `codex plugin marketplace add/list/upgrade/remove`，说明当前 WSL Codex host 已具备本地 Plugin 与 marketplace 管理入口；这不是只存在于桌面端的设想。

## 4. 当前资产全貌

### 4.1 项目级

| 资产 | 当前事实 | Plugin 相关性 |
| --- | --- | --- |
| [`AGENTS.md`](../../AGENTS.md) | Codex 仓库入口，声明架构、命令与写入边界 | 不是 Plugin 资产；应继续自动、无条件生效 |
| [`.codex/skills/`](../../.codex/skills/project/SKILL.md) | 8 个 skills，含 references 与 `agents/openai.yaml` | 直接符合 Plugin 的 `skills/` 结构 |
| [`.codex/config.toml`](../../.codex/config.toml) | Codex 侧 Serena stdio MCP + 5 工具 allowlist | MCP 定义可提取，project/runtime policy 需拆分 |
| [`.mcp.json`](../../.mcp.json) | Claude Code 侧 Serena 启动入口 | 不是 Codex Plugin 自动消费面；只能作为兼容资产保留 |
| [`.serena/project.yml`](../../.serena/project.yml) | Python/TypeScript LSP、路径、5 工具 `fixed_tools` | 可作为插件资产，但当前明显绑定 Dewflow 布局 |
| [`scripts/dev/serena-mcp.sh`](../../scripts/dev/serena-mcp.sh) | 从脚本位置解析 repo root，启动 Codex/Claude 两种 context | 可作为 MCP helper script，需参数化客户端与路径 |
| [`work-items/templates/`](../../work-items/templates/manifest.yaml) | durable task/review/debug 的模板 | 可作为 skill `assets/` 或 `references/` |
| [`scripts/qa/check_skills.py`](../../scripts/qa/check_skills.py) | 校验 frontmatter、metadata、链接和 Make target | 可成为插件自检脚本；当前硬编码 `.codex/skills` 与项目 `Makefile` |
| `.claude/settings.json` / `CLAUDE.md` | Claude 权限与路由镜像 | 跨客户端兼容层，不能由 Codex Plugin 取代 |

项目当前没有 `.codex-plugin/plugin.json`、Plugin marketplace、Plugin hooks 或 commands，说明本报告评估的是**候选提取**，不是整理已有项目 Plugin。

### 4.2 用户级

| 资产 | 当前事实 | Plugin 相关性 |
| --- | --- | --- |
| `~/.codex/config.toml:1-3` | `model`、reasoning effort、service tier | 宿主默认值，不应打包 |
| `~/.codex/config.toml:6-12` | Context7 HTTP MCP；API key 分别出现在 `headers` / `http_headers` | MCP 定义可打包；key 与重复 header 绝不能复制入包 |
| `~/.codex/config.toml:14-15` | 旧路径 `/home/tongying/workspace/dewflow` 的 trust | 用户/项目信任状态，不是 Plugin 能力 |
| `~/.codex/rules/default.rules` | 43 条命令前缀批准，含个人路径与破坏性命令 | 安全策略，不等价于 hook，不应打包 |
| `~/.codex/AGENTS.md` | 当前为空文件 | 无内容可提取 |
| `~/.codex/skills/.system/` | 5 个 OpenAI system skills | 已由 Codex 分发，不应二次封装 |
| `openai-templates` | 有 remote install marker，已经是 Plugin | 不属于待提取资产 |
| GitHub Plugin cache | 有 manifest cache、无 remote install marker | 缓存不等于已安装，不应列为当前启用能力 |

## 5. 项目级提取候选

### 5.1 A：`durable-work-items`

**拟包含**：

- `.codex/skills/task-plan/SKILL.md`
- `.codex/skills/task-plan/references/dependency-planning.md`
- `.codex/skills/task-plan/agents/openai.yaml`
- `work-items/templates/manifest.yaml`
- `work-items/templates/task-plan.md`
- `work-items/templates/review.md`
- `work-items/templates/debug.md`

**为什么适合**：

1. 工作项身份、checkpoint、workstream、open decision 和 resume interface 是通用长任务治理方法，不依赖 Dewflow 的业务架构。
2. skill 已经使用 `SKILL.md + references + agents/openai.yaml`，只需把模板移入插件 `assets/` 或 `references/`，形态与官方结构基本一致。
3. 作为 Plugin 后可按用户或团队安装，避免每个 repo 复制同一套模板。

**迁移前必须处理**：

- 将写入位置从固定 `work-items/` 抽成“默认路径 + 仓库覆盖配置”。
- 明确未安装 Plugin 的仓库是否仍允许读取既有 work-item。
- 活跃状态仍必须留在各仓库；Plugin 只携带方法和模板，不能携带 `work-items/active/`。
- Claude Code 若仍需要同一流程，应继续保留共享 skill，或提供独立的 Claude 安装/同步方案。

**结论**：技术和产品价值都最高，适合作为第一个 proof of concept。

### 5.2 B：`serena-readonly-navigation`

**拟包含**：

- Plugin `.mcp.json`：启动 Serena stdio server。
- `scripts/serena-mcp.sh`：由插件提供的通用启动器。
- `assets/project.yml.template`：只读工具策略模板。
- 可选 `skills/serena-navigation/SKILL.md`：说明何时优先语义导航、何时回退文本搜索。

**为什么适合**：

1. Plugin 官方允许包含 MCP server config；Serena 正是可独立安装和启停的工具能力。
2. 当前策略已形成稳定产品边界：只暴露 `find_declaration`、`find_referencing_symbols`、`find_symbol`、`get_diagnostics_for_file`、`get_symbols_overview`。
3. `required=false` 的静默回退行为适合在多个 repo 复用。

**当前阻碍**：

- [`.serena/project.yml:34-65`](../../.serena/project.yml) 固定 Python、TypeScript、Pyright 版本及 `frontend/apps/admin/node_modules/.bin/typescript-language-server`。
- [`scripts/dev/serena-mcp.sh:15-24`](../../scripts/dev/serena-mcp.sh) 假设脚本位于 repo 内，并同时承担 Codex / Claude Code context。
- [`.codex/config.toml:10-16`](../../.codex/config.toml) 和 `.claude/settings.json` 重复工具白名单；Plugin 只解决 Codex 分发，不能自动同步 Claude 权限。
- `.serena/project.yml` 的 `fixed_tools` 才是服务端事实源；打包时不能只复制客户端 `enabled_tools`。

**建议形态**：先做 repo marketplace Plugin，安装时检测 repo 是否存在 `.serena/project.yml`；Plugin 提供启动器和默认模板，但项目继续拥有语言/路径策略。不要把 Dewflow 的 LSP 路径作为全局默认。

### 5.3 B：`dewflow-engineering-workflows`

**拟包含**：

- `project`：项目地图和 architecture/frontend/quality/config/secrets/handoff references。
- `read`、`write`、`edit`：任务模式与写入边界。
- `add-tests`：pytest / Vitest / Playwright 分层。
- `review`：style、architecture、logic 多 pass review。
- `debug`：证据优先、批准前只读的 SRE 协议。
- 各 skill 的 `agents/openai.yaml`。

`task-plan` 建议拆到独立 Plugin，因为它的复用范围明显大于 Dewflow；Serena 也建议独立，使用户能单独启停外部工具。

**为什么能打包**：这 7 个目录已经符合标准 skill 形态，且 references 与 optional UI metadata 都是 Plugin 原生承载对象。`review`、`debug` 尤其是稳定、可版本化的工作流。

**为什么不建议立刻搬走**：

1. [`AGENTS.md:7-26`](../../AGENTS.md) 按固定路径路由 `.codex/skills/*`；删除原目录会使仓库入口失效。
2. 多个 skill 引用 `frontend/docs/`、`tests/CONVENTIONS.md`、`Makefile` 和 `.codex/skills/project/references/*`，不是自包含包。
3. 当前同一 skill 源同时供 Codex 与 Claude Code 使用；改成 Codex Plugin 会打破“双客户端单一事实源”。
4. 架构约束是进入 Dewflow 后必须成立的规则，而 Plugin 是可安装、可禁用能力。不能让用户通过关闭 Plugin 绕过 web/worker 分离或 3-tier 边界。

**推荐做法**：若目标只是当前 repo，不提取；若要服务多个 Dewflow clone、团队统一升级或在 marketplace 显式启停，则建立 **repo/team Plugin**，同时保留一个很薄的 `AGENTS.md` 和不可选的核心架构约束。可将 Plugin 作为生成/分发产物，而不是立即替代源文件。

### 5.4 C：`skill-governance` 配套能力

**拟包含**：

- 一个 `audit-skills` skill。
- `scripts/check_skills.py` 自检脚本。
- 可选 lifecycle hook，在 Plugin 更新或提交前运行确定性检查。

**为什么只是配套候选**：[`scripts/qa/check_skills.py:18-20`](../../scripts/qa/check_skills.py) 当前硬编码 repo root、`.codex/skills` 和 `Makefile`，并且测试位于项目测试树。直接打包会在其他 repo 误报。提取前需让脚本从参数或环境解析 skills root / build targets，并将脚本自身测试随 Plugin 发布。

## 6. 用户级提取候选

### 6.1 C：`context7-docs`

**可打包部分**：

- Context7 MCP 的类型与 URL。
- 可选 skill：仅在需要第三方库最新文档、版本化 API 或精确来源时使用 Context7。
- marketplace metadata：名称、描述、安装策略。

**绝不能打包**：

- `CONTEXT7_API_KEY` 的值。
- 当前 OAuth / API key 登录态。
- 用户的 model、service tier、project trust。

当前 `~/.codex/config.toml` 同时出现 `headers` 与 `http_headers` 两种 key 声明；在做 Plugin 之前应先确认 Codex 当前实际消费的字段，只保留一种声明，并改用安装时认证、宿主 secret store 或环境变量，而不是把 secret 写入 Plugin repository。

**是否值得**：单用户单机器继续保留现有 MCP 更简单；只有在以下条件之一成立时才值得做 Plugin：

- 需要在多台机器或多个 Codex host 统一启停；
- 需要给团队分发同一 MCP + 使用策略；
- 希望通过 marketplace 明确展示权限、认证时机和版本。

### 6.2 用户 skills、rules 与已安装插件

- `~/.codex/skills/.system/*` 是 OpenAI 随 Codex 分发的 system skills，已经处于受管理分发层；重新封装会造成重名、版本漂移和上下文重复。
- `~/.codex/rules/default.rules` 是宿主命令批准策略，不是 Plugin hook。特别是其中包含个人绝对路径和破坏性命令批准，复制到团队 Plugin 会扩大授权面。
- `openai-templates` 已经是 remote Plugin，无需“再次提取”。
- GitHub 仅发现缓存 manifest，没有 remote install marker；本报告不把缓存目录当成已安装或启用状态。

## 7. 明确应留在原层级的内容

| 内容 | 应留位置 | 原因 |
| --- | --- | --- |
| 核心架构与安全约束 | `AGENTS.md` + 项目标准文档 | 必须按仓库路径自动生效，不能依赖用户是否安装/启用 Plugin |
| Claude Code 路由与权限 | `CLAUDE.md`、`.mcp.json`、`.claude/settings.json` | Codex Plugin 不是 Claude Code 的配置分发协议 |
| model / reasoning / service tier | `~/.codex/config.toml` | 这是宿主执行偏好，不是某个工作流能力 |
| project trust | `~/.codex/config.toml` 或受管策略 | 属于本地安全决策，不能由可安装包自行授予 |
| 命令 allow/deny rules | `~/.codex/rules/` 或 admin policy | Plugin hook 与权限批准语义不同；打包会扩大权限 |
| API key / OAuth token | connector auth、secret store 或环境变量 | Plugin 可声明认证需求，但不能携带用户秘密 |
| 活跃 work-item | `work-items/active/` | 是仓库运行状态和协作记录，不是可复用模板 |
| 产品/架构标准正文 | `docs/`、`frontend/docs/`、`tests/CONVENTIONS.md` | 是项目事实源；复制进 Plugin 会形成双写和漂移 |

特别要避免把 `AGENTS.md` 整体“藏进” Plugin。Plugin skills 采用匹配后加载，且可以被禁用；`AGENTS.md` 则是项目级持续约束。适合迁移的是可选工作流，必须保留的是不可绕过的项目不变量。

## 8. 推荐的目标结构

如果后续决定实施，建议先用 personal/repo marketplace 做本地验证，不直接申请公共目录发布：

```text
.agents/plugins/marketplace.json
plugins/
  durable-work-items/
    .codex-plugin/plugin.json
    skills/
      task-plan/
        SKILL.md
        references/
        assets/
          manifest.yaml
          task-plan.md
          review.md
          debug.md

  serena-readonly-navigation/
    .codex-plugin/plugin.json
    .mcp.json
    skills/
      serena-navigation/
        SKILL.md
    scripts/
      serena-mcp.sh
    assets/
      project.yml.template

  dewflow-engineering-workflows/
    .codex-plugin/plugin.json
    skills/
      project/
      read/
      write/
      edit/
      add-tests/
      review/
      debug/
```

Context7 若要提取，建议放入 personal marketplace，而不是 Dewflow repo marketplace，因为它是用户跨项目偏好：

```text
~/.agents/plugins/marketplace.json
~/.codex/plugins/context7-docs/
  .codex-plugin/plugin.json
  .mcp.json
  skills/context7-docs/SKILL.md
```

以上只是目标边界，不代表本次已经创建这些目录。

## 9. 实施顺序与验收条件

### Phase 1：验证 `durable-work-items`

1. 复制并去 Dewflow 化 `task-plan`。
2. 将模板改为 skill assets，并通过 skill 内路径解析。
3. 建立 personal marketplace entry。
4. 在一个非 Dewflow 临时 repo 验证安装、显式/隐式触发、创建/恢复 work-item。
5. 确认卸载 Plugin 后，既有 `work-items/active/` 仍保持可读且不会被删除。

### Phase 2：验证 Serena MCP Plugin

1. 参数化 repo root、语言列表和 TypeScript LSP 路径。
2. 保持 `fixed_tools` 为服务端权限事实源。
3. 验证 Plugin 启用时 5 个工具可见、禁用时为 0。
4. 验证 Serena 不可用时 `required=false` 能回退普通文本搜索。
5. 单独验证 Claude Code 现有 `.mcp.json` 未受影响。

### Phase 3：决定是否发布 Dewflow workflows

只有出现至少一个明确分发需求后再做：第二个 Dewflow repo、多个团队成员需要统一安装、或希望独立版本化。否则继续保留当前 repo-local skills，更符合官方建议。

### 最低验收条件

- Plugin manifest 可被解析，name/version/path 符合官方规则。
- 安装后仅在新 chat/session 注入预期 skills/tools。
- 禁用/卸载后工具清单消失，但 connector 授权状态按宿主规则独立管理。
- 不包含 secret、用户绝对路径、project trust 或活跃任务状态。
- Skill 内所有相对链接和脚本路径在安装缓存目录中仍有效。
- Dewflow 的 `AGENTS.md` 架构边界与 Claude Code 工作流不退化。
- 项目现有 `make qa-skill-check` 或抽出的等价校验通过。

## 10. 风险与取舍

### 10.1 上下文成本

安装 Plugin 后，skill 的名称、description 和路径会进入初始 skill 清单；完整 `SKILL.md` 仅在匹配后读取。官方实现有初始 skill 清单预算，但拆成大量微型 Plugin 仍会增加发现噪音。因此建议按稳定能力域打包，而不是“一 skill 一 Plugin”。

### 10.2 双客户端漂移

当前 `.codex/skills/` 同时服务 Codex 与 Claude Code。Plugin 化若只服务 Codex，会从“一个源、两个客户端”退化成两套源。除非建立生成同步或 Claude 侧等价安装机制，否则不能删除原共享 skill。

### 10.3 权限错觉

Plugin 可声明 MCP/connector 和认证时机，但不能替代宿主 sandbox、approval policy 或外部服务 ACL。把 `default.rules` 迁成 hook 会给人“Plugin 自带授权”的错误印象，且 hook 本身还会增加执行面。

### 10.4 缓存与安装态混淆

用户目录中的 catalog checkout 或 manifest cache 只说明插件被发现或曾被同步，不能证明已安装。判断安装态至少应结合 remote install marker、当前会话工具/skill 暴露情况和 Plugin UI/CLI 状态。

### 10.5 版本与事实源

若 Plugin 复制项目标准，项目 docs 与 Plugin references 会产生双写。更稳妥的边界是：Plugin 持有通用工作流，仓库持有当前架构事实；skill 在运行时读取仓库标准，而不是复制一份快照。

## 11. 建议决策

建议当前只批准一个最小实验：**提取 `durable-work-items` 到 personal marketplace，但暂不删除仓库中的 `task-plan`**。在非 Dewflow repo 验证跨仓库价值后，再决定是否切换事实源。

其余候选保持如下状态：

- Serena：先设计参数化方案，再实施。
- Dewflow workflows：保持 repo-local，等待真实团队分发需求。
- Context7：保持用户级 MCP；除非要跨 host/团队统一安装，否则不增加 Plugin 层。
- Skill validator：随第一个自建 Plugin 一起泛化，不单独立项。

这一路径保留了 Plugin 的核心收益——可安装、可启停、可版本化、可分发——同时避免把不可选的项目约束、用户秘密和权限策略错误地产品化。

## 12. 证据索引

### 项目证据

- [`AGENTS.md`](../../AGENTS.md)：项目常驻约束与 8 个 local skills 路由。
- [`.codex/skills/project/SKILL.md`](../../.codex/skills/project/SKILL.md)：共享项目地图与 task-mode 组合。
- [`.codex/skills/task-plan/SKILL.md`](../../.codex/skills/task-plan/SKILL.md)：durable work-item 方法。
- [`work-items/templates/manifest.yaml`](../../work-items/templates/manifest.yaml)：机读状态模板。
- [`.codex/config.toml`](../../.codex/config.toml)：Codex Serena MCP 与工具 allowlist。
- [`.serena/project.yml`](../../.serena/project.yml)：语言、LSP 路径和服务端 `fixed_tools`。
- [`scripts/dev/serena-mcp.sh`](../../scripts/dev/serena-mcp.sh)：Serena 启动方式。
- [`scripts/qa/check_skills.py`](../../scripts/qa/check_skills.py)：本地 skill 合约校验器。
- [`.mcp.json`](../../.mcp.json) 与 [`.claude/settings.json`](../../.claude/settings.json)：Claude Code 兼容接线。

### 用户级证据

- `~/.codex/config.toml`：model/service tier、Context7 MCP、secret header、旧 project trust；报告仅记录字段和行号，未记录 secret 值。
- `~/.codex/rules/default.rules`：43 条主机级命令批准规则。
- `~/.codex/skills/.system/`：5 个 OpenAI system skills。
- `~/.codex/plugins/cache/openai-curated-remote/openai-templates/`：已安装 remote Plugin marker。

### 官方证据

- [Plugins](https://learn.chatgpt.com/docs/plugins)
- [Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)

## 13. 最终结论

当前配置不是“应该整体迁移成 Plugin”的单一系统，而是三层职责：

1. **仓库必须规则**：留在 `AGENTS.md`、项目 docs 和 cross-client 配置。
2. **可复用工作流与工具**：适合按 `durable-work-items`、Serena、Dewflow workflows、Context7 四个能力域逐步 Plugin 化。
3. **用户执行与安全状态**：model、trust、rules、secret、OAuth 留在宿主和授权层。

技术上可打包的范围很大；真正值得先做的范围很小。优先用 `durable-work-items` 验证 marketplace、安装/启停、版本化与跨仓库复用，再决定是否扩大，是当前风险最低且信息增益最高的路径。
