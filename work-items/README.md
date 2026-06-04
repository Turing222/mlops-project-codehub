# Work Items

`work-items/` 用于承载项目级、可提交、工具无关的任务产物。它服务于跨对话、跨 IDE、跨 agent 的协作，不依赖 `.claude/` 或单一会话上下文。

## 设计目标

- 用稳定 task identity 管理长任务，而不是按对话或 agent 切分。
- 用轻量 checkpoint 和 next choices 支撑人工随时介入。
- 让内置 `/plan` 负责大范围规划，让本目录负责持久对齐与产物回写。

## 目录约定

```text
work-items/
  active/
    <task-slug>/
      manifest.yaml
      task-plan.md
      reviews/
        <review-slug>.md
      debug/
        <debug-slug>.md
```

- `<task-slug>` 使用 kebab-case。
- 只有 `task-plan` 可以创建新的 `work-items/active/<task-slug>/`。
- `review` / `debug` 只能附着到已有 task，不负责定义 task identity。

## 什么时候需要 task

满足以下任一条件时，优先考虑创建或更新 task：

- 工作会跨多轮对话推进。
- 需要内置 `/plan` 先做大范围规划。
- 需要 review/debug checkpoint 可追踪。
- 可能交给别的 agent、IDE 或人工接手。
- 存在轻量依赖关系或明确的下一步分叉。

简单任务可直接执行，不强制进入 `work-items/`。

## manifest.yaml

`manifest.yaml` 是轻量 workflow checkpoint 卡片，不是正式 spec。建议字段：

- `slug`
- `title`
- `status`
- `goal`
- `completion_chain`
- `current_checkpoint`
- `next_choices`
- `lightweight_dependencies`
- `attached_artifacts`

它应该帮助接手者快速回答：
- 这是什么 task？
- 现在停在哪个 checkpoint？
- 当前该看哪些产物？
- 下一步有哪些合理选择？

## task-plan.md

`task-plan.md` 记录当前稳定理解：

- 当前 goal
- 已确认的对话结论
- completion chain
- workstreams
- 当前 checkpoint
- 轻量依赖
- next choices

它不应该保存完整思维过程，只保存已确认、可复用的结论。

## review / debug 产物

- `reviews/<review-slug>.md` 保存一次具体 review checkpoint 的输出。
- `debug/<debug-slug>.md` 保存一次具体 debug checkpoint 的输出。
- skill 方法论保留在 `.codex/skills/` 中，不复制到 `work-items/`。

## 复用还是新建 task

优先顺序：
1. 用户显式给出 task slug/path。
2. 存在唯一清晰的 active task 匹配。
3. 如果有歧义，先问用户。
4. 无匹配且确实需要持久跟踪时，再新建 task。

一个 task 由“稳定目标 + completion chain + 共享 checkpoint 流”定义；不要按会话切，也不要按 agent 切。
