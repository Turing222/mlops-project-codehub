---
name: review
description: "Multi-angle code review against Dewflow project skill conventions. Covers architecture, logic, naming, and style as separate passes with different context depths. Triggers on review, code review, review my code, check this, pre-commit check, /review."
---

# Code Review

Review the full current workspace change set by default, including staged changes, unstaged tracked changes, and untracked files. If the user specifies files, a commit, a PR, a diff range, or an explicit task slug/path, review only that requested scope or attach the results to that existing work item.

## Scope Gathering

Before reviewing, gather scope with:

1. `git status --short`
2. `git diff --stat`
3. `git diff`
4. `git diff --staged`
5. Read relevant untracked files listed by `git status --short`.

Do not ignore untracked files unless they are clearly scratch or generated output files, and state that exclusion explicitly.

## Review Strategy

Run reviews by dimension, from shallowest to deepest context. Shallower dimensions can run in parallel.

### Pass 1: Style & Naming (shallow — diff only)

Read the diff. Do NOT expand references or trace call chains.

Check against `.codex/skills/project/references/coding.md` conventions:

- **Naming**: banned short names (`res`, `ret`, `tmp`, `obj`, `conn`, `rid`), boolean prefix (`is_`, `has_`, `should_`, `can_`), allowed abbreviations
- **Type annotations**: public methods, endpoints, `__init__ -> None` all annotated
- **Comments**: module header format, inline comments only explain WHY/WHAT RISK, no narrative comments (`# 获取用户`, `# execute query`)
- **Error messages**: `message` in Chinese, `error_code` in UPPER_SNAKE_CASE English

### Pass 2: Architecture (medium — diff + contracts)

Read the diff + `backend/contracts/interfaces.py` + directory structure.

Check:

- Web layer (`api/`, `services/`) does NOT import from `worker/`
- Worker communication goes through `AbstractTaskDispatcher`, never `.kiq()` directly
- Dependencies injected via constructor, not global singletons
- New code follows 3-tier chain: endpoint → service → repository (no ORM queries in endpoints)
- New files placed in the correct directory per the directory map

### Pass 3: Logic & Correctness (deep — expand references as needed)

Read the diff. For each changed function, identify its callers and callees. Expand references when something looks suspicious.

Check:

- **None guards**: repository/service methods returning `T | None` are guarded before attribute access
- **Async correctness**: sync blocking I/O wrapped in `await asyncio.to_thread()`, no `async def` without `await`
- **Transaction boundary**: writes are within UoW commit scope, rollback on failure
- **Error handling**: exceptions caught at the right layer, no bare `except: pass`
- **Resource cleanup**: file handles, Redis connections, DB sessions properly closed
- **Idempotency**: duplicate requests handled safely (check for `idempotency_lock_key` patterns)

## Output Format

用中文按 pass 分组输出，不使用表格。每个 finding 用编号文本，包含严重级别、文件行号、问题和修复建议。

严重级别：

- `必须修复`：违反 CRITICAL 规则，或会导致实际 bug。
- `建议修复`：违反约定，或降低可维护性。
- `提示`：观察项，可选改进。

Good template:

```md
## Review: workspace changes
Scope: staged + unstaged + untracked files from `git status --short`.

### 风格与命名
未发现问题。

### 架构
未发现问题。

### 逻辑与正确性

1. [建议修复] `backend/config/schemas/prompts.py:24`
   问题：`PromptTemplateDefinition.content` 使用了会返回 `strip()` 后内容的 validator，会改变 prompt 模板首尾空白。
   修复建议：保留非空校验，但返回原始字符串。
```

## Work-Item Attachment

- If the user gives an explicit `work-items/active/<task-slug>/` path or task slug, attach persisted review output to that existing task.
- If there is exactly one clear active-task match, you may attach to it.
- If there are multiple plausible matches, ask the user which task to use.
- If no task exists yet, do not create one from `review` alone; suggest using `task-plan` when durable tracking is needed.
- Persist the concrete review checkpoint output only; keep review methodology in this skill file, not inside `work-items/`.

## Rules

- Only report actual problems.
- When a pass has **no findings**: write `未发现问题。` only. Do NOT list verified items or "all changes align" commentary — a clean pass speaks for itself.
- When a pass has **findings**: use numbered text. One numbered item per finding.
- Do NOT re-state project rules in findings — reference them by name (e.g. "violates naming: banned short name `res`")
- When a finding spans multiple lines, reference the first line
- Architecture violations are always `必须修复`
- Never combine unrelated issues into one finding
