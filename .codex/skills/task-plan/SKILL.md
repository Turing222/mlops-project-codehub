---
name: task-plan
description: Create or update durable work-item artifacts for Dewflow. Use when the user wants to align a long-running work item, persist approved `/plan` conclusions, track workstreams or open decisions, update checkpoints, resume paused work, attach the current request to an existing work-item slug/path, or plan multi-stage/multi-PR work such as layered security, deployment, CI, monitoring, performance, or architecture changes.
---

# Task Plan

Use this skill to maintain durable work-item artifacts under `work-items/` without competing with Claude Code built-in `/plan`.

## Core Positioning

- Prefer built-in `/plan` for broad, ambiguous, architectural, or long-running planning.
- Skip this skill for simple work that can be executed directly without durable tracking.
- Use this skill when the work needs a stable work-item identity, cross-conversation handoff, dependency tracking, or checkpoint updates.
- For multi-stage or multi-PR plans, load this skill and ask whether to persist the plan if the user has not already said to write `work-items/` artifacts.

## Complex Task Gate

Treat a request as complex enough to offer durable tracking when it has two or more signals:

- multiple PRs, workstreams, layers, or phases;
- security, deployment, CI, monitoring, migration, performance, or architecture scope;
- cross-day or cross-conversation follow-up;
- explicit dependencies, checkpoints, acceptance criteria, or rollout sequencing;
- wording such as "方案", "计划", "里程碑", "分层修复", "后续推进", "roadmap", or "PR 拆分".

If the task looks complex but persistence is not explicit, ask one concise question before creating files: "这个方案只在对话里确认，还是创建 `work-items/active/<slug>/` 持久化跟踪？"

## Core Flow

1. Confirm the work needs durable tracking rather than a one-off answer or direct edit.
2. Resolve work-item identity in this order:
   - explicit work-item slug/path from the user;
   - one clear match from existing `work-items/active/*/manifest.yaml` files;
   - ask one concise question if there are multiple plausible matches;
   - create a new work item only when no match exists and durable tracking is desired.
3. Load the artifact schema before writing:
   - for a new work item, read and copy the structure of `work-items/templates/manifest.yaml` and `work-items/templates/task-plan.md`;
   - for an existing work item, read its `manifest.yaml` first, then its `task-plan.md` and any attached artifact relevant to the request;
   - preserve the template field names, enum values, and separation between machine state and human narrative.
4. Create or update the work-item artifacts:
   - `work-items/active/<work-item-slug>/manifest.yaml`
   - `work-items/active/<work-item-slug>/task-plan.md`
5. Record the stable goal, completion chain, workstreams, current checkpoint, open decisions, attached artifacts, and next choices.
6. Sync only confirmed conclusions from the conversation or built-in `/plan`; do not dump full reasoning traces into the repo.
7. If executable work is requested after alignment, switch to `write`, `edit`, or `add-tests`, or use built-in `/plan` first when the task still needs broad planning.

## Work-Item Identity Rules

- Only this skill creates a new `work-items/active/<work-item-slug>/` directory.
- A work item is defined by a stable goal, a completion chain, and a shared checkpoint flow — not by conversation boundaries or which agent handled it.
- If the work can be completed, reviewed, or handed off independently, prefer a separate work item slug.
- If the user later changes the goal substantially, create a new work item instead of rewriting history into the old one.

## Artifact Contract

- `manifest.yaml` is the machine-readable source of truth for state: `status`, `workstreams[].status`, `current_checkpoint`, `next_choices`, and `open_decisions`. Read it first when resuming a work item.
- `task-plan.md` is the human narrative: goal intent, conversation conclusions, per-workstream rationale, and out-of-scope notes. It never duplicates the manifest's state fields.
- Language contract: keep `manifest.yaml` fully English, including narrative values such as `goal`, `title`, `summary`, `label`, and `note`; write `task-plan.md` prose in Chinese while preserving code symbols, commands, status values, and technical terms in English.
- `workstreams` is a structured list in `manifest.yaml`. Each entry has `id`, `title`, `status` (`pending | in_progress | done | deferred`), `kind` (`blocking | parallel | serial`), and `deps` (ids it waits on). Per-workstream progress lives here, not in prose.
- Keep two dependency concepts separate: `deps` is workstream ordering; `open_decisions` is unresolved questions or prerequisites.
- `current_checkpoint.state` uses `planned | in_progress | implemented | validated`.
- `next_choices` ids are sequential (`A`, `B`, `C`); do not skip letters.
- `review` and `debug` artifacts attach to an existing work item; they do not create work-item identity.
- Use kebab-case work-item slugs.

## Progressive Disclosure

- Read [references/dependency-planning.md](references/dependency-planning.md) for dependency labels, checkpoint heuristics, and workstream examples.
- Read [`work-items/templates/manifest.yaml`](../../../work-items/templates/manifest.yaml) and [`work-items/templates/task-plan.md`](../../../work-items/templates/task-plan.md) before creating a work item.
