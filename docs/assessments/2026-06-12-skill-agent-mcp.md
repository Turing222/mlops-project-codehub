# Skill / Agent / MCP 评估报告

> 日期：2026-06-12
> 范围：`.codex/skills/`、`agents/openai.yaml`、`.agents/` 与 Serena MCP 接线
> 性质：只读评估，未改动任何运行逻辑文件。
> 证据基线：分支 `feat/frontend-v1` 的项目级 agent 配置与 skill 资产
> 状态：冻结；后续现行约定以 `.codex/skills/` 与 `AGENTS.md` 为准

## 1. 体系全貌

Dewflow 用 **双入口路由** 喂两个 agent 客户端：

- `CLAUDE.md` → Claude Code 的路由索引
- `AGENTS.md` → Codex 的路由索引

两者内容几乎逐条对齐，共享同一套技能库 `.codex/skills/`（8 个技能：`project / read / write / edit / add-tests / review / debug / task-plan`）。技能采用 **渐进式披露**：SKILL.md 只放路由 + 核心流程，细节沉到 `references/*.md`，符合 "keep the index short" 的设计意图。

MCP 侧只接了一个服务：**Serena**（语义导航 + 诊断），通过 `scripts/dev/serena-mcp.sh` 同时服务 `codex` 和 `claude-code` 两个 context，工具集被收窄为 5 个只读符号工具。

整体结构清晰、职责单一，是一套设计良好的"单一技能源 + 多客户端路由 + 单一只读 MCP"架构。下面按维度给出问题与建议。

## 2. Serena MCP 接线

**做得好的地方**——三重防线把 Serena 锁死在"只读语义导航"，且三层一致：

1. `scripts/dev/serena-mcp.sh` 启动参数：`--mode no-memories`、关闭 web dashboard。
2. `.serena/project.yml` 的 `fixed_tools` 只暴露 5 个工具（`find_declaration / find_referencing_symbols / find_symbol / get_diagnostics_for_file / get_symbols_overview`），`initial_prompt` 明确"只做语义导航与诊断，编辑/命令/校验留给宿主"。
3. `.codex/config.toml` 的 `enabled_tools` 与 `.claude/settings.json` 的 `allow` 列表，两个客户端各自又重复声明了同一份 5 工具白名单。
4. `.claude/settings.json` 的 `deny` 额外显式拒绝了 9 个写类工具（`write_memory / replace_symbol_body / rename_symbol / insert_*` 等）——纵深防御，即便上游配置漂移也兜底。

**问题与风险**：

- **P2 — 白名单四处重复，无单一事实源**：同一份 5 工具清单同时硬编码在 `project.yml(fixed_tools)`、`config.toml(enabled_tools)`、`settings.json(allow)` 三个文件。新增/删除一个 Serena 工具要改三处，极易漂移。`project.yml` 的 `fixed_tools` 其实已是服务端硬约束，客户端两份 `allow/enabled_tools` 更多是"免确认弹窗"用途——建议在文档里点明哪份是事实源（`fixed_tools`），其余仅为体验优化。
- **P3 — `.claude/settings.json` 的 deny 列表是"防君子"冗余**：因为 `fixed_tools` 已经让那 9 个写工具根本不会被 Serena 暴露，deny 实际拦不到东西。保留无害（防 `fixed_tools` 被误删），但应注释说明其为兜底，否则后人会误以为这些工具本来可用。
- **P3 — `required = false` + `startup_timeout 60s`**：Codex 侧 Serena 非必需、启动超时静默降级。好处是不阻塞；风险是 Serena 没起来时 agent 会"静默退回纯文本搜索"而无告警。建议确认这是有意为之（对 WSL/慢启动友好）。

## 3. 技能体系（`.codex/skills/*/SKILL.md`）

**做得好的地方**：

- frontmatter 的 `description` 写得"触发导向"（列了大量动词/中文触发词），利于客户端自动选技能。
- `review` 与 `debug` 是两个最成熟的技能：`review` 分 3 个 pass（风格→架构→逻辑）按上下文深度递进，浅层可并行；`debug` 用 SRE 式"证据优先 + 批准前禁写"协议，三条 FAILURE CONDITION 和中文输出模板都很硬核。这两个技能质量明显高于其余 6 个流程型技能。
- 架构边界（web/worker 分离、3 层调用链、`AbstractTaskDispatcher`）在 `project / edit / debug / review` 里反复强化，护栏一致。

**问题与风险**：

- **P1 — 已处理：Codex 专用术语泄漏到通用技能里**：`read/SKILL.md` 与 `debug/SKILL.md` 原先把 `apply_patch` 列为"禁止的写操作"。当前已改成客户端中性表述，如"任何写文件/改文件的操作（编辑、新建、`sed -i`、重定向写入等）"。
- **P2 — 已处理：名义 vs 实际工具不一致**：`read/SKILL.md` 原先指示用 `rg / rg --files / sed -n / ls`。当前已改成"available read-only tools"这类工具中性描述，保留 `rg`/`sed -n` 作为示例而不是硬性要求。
- **P3 — 已处理：`read` / `project` 技能的"backend"标签名不副实**：两者 description 当前均已明确覆盖 Dewflow repository / monorepo，不再限定 backend；`task-mode.md` 也明确所有 mode 同时覆盖前后端。

## 4. `agents/openai.yaml` 与 `.agents/` 目录

`task-mode.md` 已明确定位：每个技能的 `agents/openai.yaml` 只是 **Codex/OpenAI agent 列表的 UI 元数据**（`display_name / short_description / default_prompt`），不是运行时代码。这个定位是对的，文件本身也都很薄。

**问题与风险**：

- **P2 — `agents/openai.yaml` 对 Claude Code 完全是死文件**：8 份 yaml 纯为 Codex UI 服务，Claude Code 不读取。它们与 SKILL.md frontmatter 存在信息重复（都描述技能用途），且会各自漂移——例如 `read.yaml` 的 `default_prompt` 说 "Inspect the repository context"，而 SKILL.md 强调只读边界，两边约束粒度不同。建议：要么接受其为纯 Codex 装饰物并在 `task-mode.md` 里再强调一次"勿当作 Claude 配置"，要么用脚本从 SKILL.md frontmatter 生成以杜绝漂移。
- **P3 — 早期 yaml 与后期 yaml 风格不一**：`project/read/edit/write/add-tests` 的 yaml 是单行简短 prompt；`review/debug/task-plan` 的 prompt 明显更长更具体（后补的）。无功能影响，但说明这批文件是分阶段手写、缺乏统一模板。
- **P1 — 根目录 `.agents/` 是空目录且未被 git 跟踪**：`git ls-files .agents` 无输出、目录内零文件。它既不是 Claude 的 subagent 目录（那是 `.claude/agents/`），也不是 Codex 技能目录（那在 `.codex/skills/*/agents/`）。这是一个 **孤儿空目录**——要么是某次重构遗留，要么是预留未实现。建议删除，或放一个 `.gitkeep` + README 说明用途，否则会持续误导"这里应该有 agent 配置"。

## 5. 问题汇总与优先级

| # | 级别 | 问题 | 建议动作 |
| --- | --- | --- | --- |
| 1 | P1 | `read`/`debug` SKILL.md 把 Codex 专用 `apply_patch` 当禁令，Claude 侧落空 | 已改为客户端中性的写操作描述 |
| 2 | P1 | 根目录 `.agents/` 空目录、未跟踪、无用途 | 删除，或 `.gitkeep`+README 说明 |
| 3 | P2 | Serena 工具白名单四处重复无单一事实源 | 文档点明 `fixed_tools` 为事实源，其余仅免确认 |
| 4 | P2 | `read`/`project` description 标 "backend" 但实际覆盖前端 | 已去掉 backend 限定词 |
| 5 | P2 | `agents/openai.yaml` 对 Claude 是死文件、与 frontmatter 漂移 | 接受为 Codex 装饰物并强调，或脚本生成 |
| 6 | P3 | `settings.json` deny 列表是 `fixed_tools` 之上的冗余兜底 | 加注释说明为防御性兜底 |
| 7 | P3 | 技能写死 `rg/sed -n` 等命令名而非工具中性意图 | 已改为工具中性描述，命令仅作示例 |
| 8 | P3 | yaml 风格新旧不一 / Serena `required=false` 静默降级 | 统一模板；确认降级为有意 |

## 6. 结论

体系**骨架健康**：单一技能源 + 双客户端路由 + 锁死只读的 Serena MCP，护栏（架构边界、禁写协议、工具白名单）层层一致，`review`/`debug` 两个技能尤其成熟。

主要短板集中在 **"双客户端共享单边假设"**：技能库整体是为 Codex 起草、再复用给 Claude Code，曾导致 `apply_patch`、`agents/openai.yaml`、命令名等 Codex-specific 内容渗入共享层，对 Claude 侧或失效或冗余。其中 `apply_patch` 和命令名表述已改为中性描述；孤儿 `.agents/` 空目录和 Serena 白名单重复仍是核心待办。

优先处理剩余 P1 项（孤儿目录）即可消除最可能误导 agent 的隐患；P2/P3 为一致性与可维护性优化，可随手清理。
