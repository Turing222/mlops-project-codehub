---
name: project
description: Dewflow monorepo project rules and context for backend and frontend. Use for any work in this repository when the agent needs architecture boundaries, directory ownership, coding conventions, quality gates, operational constraints, commit guidance, or response handoff rules.
---

# Project

Use this skill as the shared project map. Load only the reference needed for the current task.

## References

- [context.md](references/context.md): project overview and directory map.
- [frontend.md](references/frontend.md): frontend stack, directory map, standards index, and validation commands.
- [architecture.md](references/architecture.md): web/worker split, dependency injection, and 3-tier call chain.
- [coding.md](references/coding.md): naming, typing, async, comments, and errors.
- [config-policy.md](references/config-policy.md): when to use config, YAML, settings, or code constants.
- [secrets-and-flags.md](references/secrets-and-flags.md): secret file injection, smoke secret wiring, and feature flag governance.
- [quality.md](references/quality.md): Make targets, `uv run`, Docker checks, and command constraints.
- [handoff.md](references/handoff.md): change summary and commit message conventions.
- [task-mode.md](references/task-mode.md): mode selection, skill collaboration, and `agents/openai.yaml` purpose.

## Use With Mode Skills

After loading the relevant project reference, load exactly one task-mode skill unless the user request clearly needs more:

- `read` for read-only analysis.
- `task-plan` for durable work-item alignment, dependency-aware checkpointing, and syncing approved `/plan` conclusions into `work-items/`.
- `write` for new files or new capability surfaces.
- `edit` for modifying existing files.
- `add-tests` for test coverage (pytest / Vitest / Playwright).
- `review` for code review of diffs, commits, or PRs.
- `debug` for evidence-first troubleshooting of faults and incidents.

Route fix / troubleshooting / review ambiguity per the Fix & Troubleshooting Routing section in [task-mode.md](references/task-mode.md).

After `write` or `edit`, consider `add-tests` if behavior changed or coverage gaps exist.
