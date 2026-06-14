---
name: edit
description: Modify existing Dewflow files safely. Use when the user asks to change, fix, update, refactor, rename, remove, or adjust existing code, docs, config, scripts, migrations, or local skills; use add-tests for test-only changes.
---

# Edit

Use this skill when the primary task is changing existing files.

## Core Flow

1. Identify the owning stack, then load the matching project reference: `architecture.md` for backend, `frontend.md` for frontend.
2. Read the target files and nearby tests before editing.
3. Check `git status --short` so user changes are not overwritten.
4. Apply the smallest coherent patch that satisfies the latest request.
5. Preserve architecture boundaries — backend: endpoint → service → repository, and web → dispatcher → worker; frontend: pages compose only, API calls via `src/api`, streams in `src/streams`.
6. Do not add bare `while True`; use an explicit bounded loop with a clear exit path.
7. Run focused validation first (`make qa-*` for backend, `make frontend-*` for frontend), then broader checks only when the change risk justifies it.
8. If behavior changed or coverage gaps are exposed, consider loading `add-tests`.
9. If files were modified, append the Change Summary block from `.codex/skills/project/references/handoff.md`.

## Progressive Disclosure

- Read [references/edit-existing.md](references/edit-existing.md) for edit safety, boundary checks, and validation selection.
