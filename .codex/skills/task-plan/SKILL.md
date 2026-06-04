---
name: task-plan
description: Create or update durable work-item artifacts for Dewflow. Use when the user wants to align a long-running task, persist approved `/plan` conclusions, track lightweight dependencies, update checkpoints, resume paused work, or attach the current request to an existing task slug/path.
---

# Task Plan

Use this skill to maintain durable task artifacts under `work-items/` without competing with Claude Code built-in `/plan`.

## Core Positioning

- Prefer built-in `/plan` for broad, ambiguous, architectural, or long-running planning.
- Skip this skill for simple work that can be executed directly without durable tracking.
- Use this skill when the work needs a stable task identity, cross-conversation handoff, dependency tracking, or checkpoint updates.

## Core Flow

1. Confirm the work needs durable tracking rather than a one-off answer or direct edit.
2. Resolve task identity in this order:
   - explicit task slug/path from the user;
   - one clear match from existing `work-items/active/*/manifest.yaml` files;
   - ask one concise question if there are multiple plausible matches;
   - create a new task only when no match exists and durable tracking is desired.
3. Create or update the task artifacts:
   - `work-items/active/<task-slug>/manifest.yaml`
   - `work-items/active/<task-slug>/task-plan.md`
4. Record the stable goal, completion chain, current checkpoint, lightweight dependencies, attached artifacts, and next choices.
5. Sync only confirmed conclusions from the conversation or built-in `/plan`; do not dump full reasoning traces into the repo.
6. If executable work is requested after alignment, switch to `write`, `edit`, or `add-tests`, or use built-in `/plan` first when the task still needs broad planning.

## Task Identity Rules

- Only this skill creates a new `work-items/active/<task-slug>/` directory.
- A task is defined by a stable goal, a completion chain, and a shared checkpoint flow — not by conversation boundaries or which agent handled it.
- If the task can be completed, reviewed, or handed off independently, prefer a separate task slug.
- If the user later changes the goal substantially, create a new task instead of rewriting history into the old one.

## Artifact Contract

- `manifest.yaml` is a lightweight checkpoint card, not a formal spec.
- `task-plan.md` is the durable summary of current understanding, workstreams, dependencies, and next choices.
- `review` and `debug` artifacts attach to an existing task; they do not create task identity.
- Use kebab-case task slugs.

## Progressive Disclosure

- Read [references/dependency-planning.md](references/dependency-planning.md) for dependency labels, checkpoint heuristics, and workstream examples.
