# Handoff Rules

## Change Summary

If files were modified during the turn, append this block after the normal response:

```md
## Change Summary
**What**: [one sentence no more than 30 words, same language as the conversation]
**Why**: [key decision or trade-off]
**Affected**: [1-3 files/modules touched]
```

Use Chinese for Change Summary when the conversation is Chinese. Keep file paths,
commands, code symbols, and status values in English.

## Commit Messages

Use Conventional Commits. Keep the subject in English and no more than 50 characters.

```text
type[(scope)]: English summary

- Why this approach
- Alternatives considered / risks
```

Types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`.

Default to a body for code, config, or deploy changes. Omit the body only for truly trivial docs or tests.

Commit bodies may use Chinese for project-internal reasoning. Keep commands,
identifiers, and error codes in English.

## Pre-Commit Checklist

- Referenced files: if Makefile targets, imports, or `bash scripts/...` references were added, verify those files are staged; `git status` shows new files as untracked.
- Scratch files: review untracked files for temporary tests, `.env` variants, and debug scripts.
- Stage by name: always use `git add <specific files>`, never `git add .` or `git add -A`.

## Example

```text
refactor(chat): offload non-stream generation

Move non-stream LLM generation into the worker path so web requests share the same persistence and timeout behavior as streaming.

Keep the web workflow responsible for session setup and task dispatch to preserve the web/worker import boundary.
```
