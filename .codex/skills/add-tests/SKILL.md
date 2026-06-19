---
name: add-tests
description: Add or update test coverage for Dewflow. Use when the user asks to add tests, improve coverage, test a bug fix, write unit/component/integration/e2e tests, or verify behavior with pytest (backend) or Vitest/Playwright (frontend).
---

# Add Tests

Use this skill for test-only work or test coverage paired with a code change.

## Core Flow

1. Identify what behavior changed or needs protection, and which stack owns it (backend or frontend).
2. Read nearby tests, fixtures, and test conventions before adding files. For backend, `tests/CONVENTIONS.md` is the authoritative writing standard (placement, naming, fixtures, markers, async, assertions).
3. Choose the lowest test layer that proves the behavior.
4. Mirror existing fixture, marker, naming, and assertion style.
5. Run the focused test command (`uv run pytest ...` for backend; `make frontend-test` or `make frontend-e2e-mock` for frontend), or explain why it was not run.
6. If files were modified, append the Change Summary block from `.codex/skills/project/references/handoff.md`.

## Progressive Disclosure

- `tests/CONVENTIONS.md` is the single source of truth for backend test-writing rules; `tests/README.md` covers directory layout and run commands. Defer to them rather than restating their rules here.
- Read [references/pytest-layering.md](references/pytest-layering.md) for the skill-specific layer-selection heuristic and verification commands.
- Read [references/frontend-testing.md](references/frontend-testing.md) for frontend test layer, placement, mock data, and verification commands.
