# Work Items

`work-items/` 用于承载项目级、可提交、工具无关的工作项（work item）产物。它服务于跨对话、跨 IDE、跨 agent 的协作，不依赖 `.claude/` 或单一会话上下文。

## 设计目标

- 用稳定 work-item identity 管理长任务，而不是按对话或 agent 切分。
- 用轻量 checkpoint 和 next choices 支撑人工随时介入。
- 让内置 `/plan` 负责大范围规划，让本目录负责持久对齐与产物回写。

## 目录约定

```text
work-items/
  active/
    <work-item-slug>/
      manifest.yaml
      task-plan.md
      reviews/
        <review-slug>.md
      debug/
        <debug-slug>.md
```

- `<work-item-slug>` 使用 kebab-case。
- 只有 `task-plan` 可以创建新的 `work-items/active/<work-item-slug>/`。
- `review` / `debug` 只能附着到已有 work item，不负责定义 work-item identity。

## 什么时候需要 work item

满足以下任一条件时，优先考虑创建或更新 work item：

- 工作会跨多轮对话推进。
- 需要内置 `/plan` 先做大范围规划。
- 需要 review/debug checkpoint 可追踪。
- 可能交给别的 agent、IDE 或人工接手。
- 存在轻量依赖关系或明确的下一步分叉。

简单任务可直接执行，不强制进入 `work-items/`。

## manifest.yaml

`manifest.yaml` 是机读真相源（machine source of truth），承载所有状态字段。它面向 agent / 自动化恢复，整体使用英文：字段名、枚举、状态值，以及 `title` / `goal` / `summary` / `label` / `note` 等叙述值都写英文。字段：

- `slug`
- `title`
- `status`
- `goal`
- `completion_chain`：验收标准（done 的定义）
- `workstreams`：执行单元 + 机读状态，每条含 `id` / `title` / `status` / `kind` / `deps`
- `current_checkpoint`
- `open_decisions`：尚未拍板的问题或前提（不是任务排序）
- `next_choices`：恢复接口，id 连续 A/B/C
- `attached_artifacts`

它应该帮助接手者快速回答：
- 这是什么 work item？
- 现在停在哪个 checkpoint？每条 workstream 是什么状态？
- 当前该看哪些产物？
- 下一步有哪些合理选择？

状态只写在这里。`task-plan.md` 不复制这些字段，避免两份漂移。

## task-plan.md

`task-plan.md` 是工作项的人读叙述（human narrative），正文使用中文，只记录“为什么、范围、取舍”。代码标识、命令、字段名、状态枚举和常用技术术语保留英文：

- goal 背后的意图
- 已确认、去重的对话结论
- 每条 workstream 的 Scope / Reason / Expected effect（按 manifest 的 workstream id 对应）
- Deferred / Out of Scope
- open decisions 的展开说明

它不保存完整思维过程，也不复制 manifest 的状态字段（status / workstreams 状态 / checkpoint / next_choices）。

## review / debug 产物

- `reviews/<review-slug>.md` 保存一次具体 review checkpoint 的输出。
- `debug/<debug-slug>.md` 保存一次具体 debug checkpoint 的输出。
- skill 方法论保留在 `.codex/skills/` 中，不复制到 `work-items/`。

## 复用还是新建 work item

优先顺序：
1. 用户显式给出 work-item slug/path。
2. 存在唯一清晰的 active work item 匹配。
3. 如果有歧义，先问用户。
4. 无匹配且确实需要持久跟踪时，再新建 work item。

一个 work item 由“稳定目标 + completion chain + 共享 checkpoint 流”定义；不要按会话切，也不要按 agent 切。
