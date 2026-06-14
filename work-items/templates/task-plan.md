# 工作项计划：人类可读工作项标题

> 机读状态（`status`、`workstreams`、`current_checkpoint`、`next_choices`、
> `open_decisions`）只保存在 `manifest.yaml`，并以它为准。
> 本文件只记录稳定叙事：为什么做、范围是什么、取舍是什么。
> 不要在这里复制状态字段。

## 目标

用一段中文解释这个工作项目标背后的意图，不要逐字复制 `manifest.yaml` 里的单行 `goal`。

## 对话结论

- 已确认、去重后的稳定结论。
- 重要决策或约束。

## Workstream 拆分理由

每一节对应 `manifest.yaml` 中的一个 workstream id。这里只写这个工作项下各 workstream 的范围和理由；状态只保存在 manifest。

### WS1 — manifest 中的标题

- Scope：这个 workstream 改什么。
- Reason：为什么需要它。
- Expected effect：完成后应成立的结果。

### WS2 — manifest 中的标题

- Scope：...
- Reason：...
- Expected effect：...

## 暂缓 / 不纳入范围

- 明确排除的工作和简短理由。这些不是 workstream。

## Open Decisions 说明

- `example-decision`：展开 manifest 中的条目，说明背景和当前倾向。
