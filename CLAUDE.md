# CLAUDE.md — Dewflow Backend

This file is the lightweight routing index for Claude Code. Project rules live in `.codex/skills/project/` (shared with Codex). Load references on demand instead of expanding this file.

## Always

- Before backend work, read `.codex/skills/project/SKILL.md`, then load the smallest matching task skill below.
- Do not modify files unless the user explicitly asks for implementation, code changes, or file edits.
- Preserve the web/worker split: web code dispatches through `AbstractTaskDispatcher`, never imports `backend.worker`, and never calls `.kiq()` directly.
- Preserve the 3-tier call chain: endpoint -> service -> repository -> ORM.
- Use `uv run` for Python commands; cap noisy output with `| head -200`.
- Do not browse localhost; use `curl` for local health checks.
- If files were modified, append the Change Summary block defined in `.codex/skills/project/references/handoff.md`.

## Task Skills

- Project rules: `.codex/skills/project/SKILL.md`
- Read-only analysis or explanation: `.codex/skills/read/SKILL.md`
- Durable task alignment and work-item artifacts: `.codex/skills/task-plan/SKILL.md`
- Creating new code/docs/config/skill assets: `.codex/skills/write/SKILL.md`
- Modifying existing files: `.codex/skills/edit/SKILL.md`
- Adding or updating pytest coverage: `.codex/skills/add-tests/SKILL.md`
- Code review: `.codex/skills/review/SKILL.md`
- Debugging or bug investigation: `.codex/skills/debug/SKILL.md`

## Skill Loading

- For broad implementation work, prefer Claude Code built-in `/plan`; use `task-plan` when you need to create/update `work-items/` artifacts or sync approved planning conclusions.
- For review or debug requests, load the named skill and any project reference it asks for.
- After `write` or `edit`, consider `add-tests` if behavior changed or coverage gaps exist.
- Simple tasks may skip `task-plan` and proceed directly to the smallest execution skill.
- Keep this file short; move durable details into `.codex/skills/project/references/` instead of expanding it.
