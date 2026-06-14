# Coding Conventions

## Naming

- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Boolean prefix: `is_`, `has_`, `should_`, `can_`
- All identifiers in English
- Allowed abbreviations: `id`, `db`, `llm`, `rag`, `kb`, `s3`, `ip`, `url`, `api`, `http`, `jwt`, `otel`
- Banned short names: `res`, `ret`, `tmp`, `obj`, `conn`, `rid`

## Type Annotations

- HTTP endpoints must annotate return type.
- Dependency providers must annotate return type.
- Service and repository public methods must annotate return type.
- `__init__` must annotate `-> None`.
- Private helpers should be annotated opportunistically when touched.
- Do not introduce complex type aliases just for completeness.

## Async / Sync

- Default to `def`; use `async def` only when `await` is needed.
- Use `@staticmethod` when a method does not access `self`.
- Wrap sync blocking I/O in async context with `await asyncio.to_thread(...)`.
- Use process pools or background tasks for CPU-bound work.

## Comments And Errors

- Module header: one English sentence summary plus Chinese responsibilities, boundaries, and side effects.
- Class/function docstrings: one sentence max if the module header already covers responsibilities.
- Inline comments explain why or risk only.
- User-visible `message` fields are Chinese and never expose internals.
- Developer logs and internal exception messages are English; use stable English `event` or `error_code` fields for alerting and search.
- `error_code` is `UPPER_SNAKE_CASE` English.
- `details` keys are `snake_case`; stringify UUIDs.

## Language Boundaries

- Code-facing artifacts use English: identifiers, filenames, API fields, config keys, test names, developer logs, internal exceptions, skill control instructions, `AGENTS.md`, commit subjects, and `work-items/*/manifest.yaml` narrative values.
- Skill trigger examples, user-facing output templates, and approval phrases may use the target conversation language.
- Human-facing project docs use Chinese prose: root README, `docs/**`, PR descriptions, review reports/comments, Change Summary, and `work-items/*/task-plan.md`.
- Keep commands, code symbols, field names, status values, and common technical terms in English inside Chinese prose.
- Do not maintain mirrored bilingual paragraphs. If quick local context is needed in code/config, use a short module header or document link instead of line-by-line translation.
