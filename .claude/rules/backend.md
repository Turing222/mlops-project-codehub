---
paths:
  - "backend/**"
  - "alembic/**"
---

# Backend Rules

Distilled from `.codex/skills/project/references/architecture.md`.

## 3-tier call chain (default path)

- `endpoint -> service -> repository -> ORM`. Endpoints own HTTP only; services
  own business logic; repositories own SQLAlchemy queries.
- Never query ORM models directly from endpoints.
- Exception: `backend/application/` workflows may run
  `endpoint -> workflow -> service / repository` and use `AbstractUnitOfWork`
  repositories directly for persistence (see `application/chat/web_stream_workflow.py`).
  This is an allowed pattern, not a tier violation.

## Web / worker split (enforced by scripts/check_import_boundaries.py)

- Web code (`backend.api`, `backend.services`, `backend.middleware`) depends on
  `contracts/interfaces.py`, never imports `backend.worker`.
- Web -> worker only through `AbstractTaskDispatcher`; dispatch via
  `task_dispatcher.enqueue_*()`, never `.kiq()` directly from web code.
- Web-side workflows in `backend/application/` must not import `backend.worker`.

## Dependency injection

- DI factories live in `api/deps/`. Services receive dependencies via `__init__`,
  not global singletons.
- `AbstractUnitOfWork` wraps transactions/repositories; repository methods take
  `session` as an explicit parameter.

## Python

- Prefix Python commands with `uv run`. Use `async def` only when `await` is needed;
  wrap sync blocking I/O with `await asyncio.to_thread(...)`.
- No bare `while True` — use a bounded loop with a clear exit path.

## Validate

- `make qa-*` for focused checks, `make flow-fast` for the default local gate.

Full rationale: architecture.md, coding.md, quality.md.
