# Editing Rules (all files)

Distilled, always-on editing rules. Full rationale in
`.codex/skills/project/references/` (coding.md, handoff.md, quality.md).

## Before editing

- Read the target file and nearby tests first.
- `git status --short` so user edits are not overwritten.

## Smallest coherent patch

- Apply the minimal change that satisfies the request.
- No drive-by refactors outside the request scope.

## Comments and density

- Match the comment density, naming, and idiom of the file you are editing.
- Do NOT add multi-line explanatory comments to fields/lines that have none nearby.
- Inline comments explain a non-obvious *why* or risk only. A why that needs a
  paragraph belongs in the commit message or a work-item note, not inline.

## Naming and language

- `snake_case` vars/functions, `PascalCase` classes, `UPPER_SNAKE_CASE` constants;
  identifiers in English. Banned short names: `res`, `ret`, `tmp`, `obj`, `conn`, `rid`.
- Code-facing artifacts (identifiers, fields, config keys, logs, `error_code`) are English.
- User-visible `message` is Chinese and never exposes internals.

## No auto-commit

- Stage by name (`git add <file>`), never `git add .` / `git add -A`.
- Commit/push only when the user explicitly asks.

## Destructive changes

- Before suggesting deletion of configs, databases, backups, logs, chat/session
  history, credentials, or app state directories, warn about data loss and
  recommend a backup or non-destructive check first.

## After editing

- Validate: backend `uv run` / `make qa-*`; frontend `make frontend-*` (pnpm only).
  Cap noisy output with `| head -200`.
- Append the Change Summary block (What / Why / Affected) from handoff.md; Chinese
  when the conversation is Chinese, paths/commands/symbols stay English.
