# Architecture Rules

## Web / Worker Split

- Web code in `backend.api`, `backend.services`, and `backend.middleware` depends on `contracts/interfaces.py`, not `backend.worker`.
- Worker code in `backend.worker` may depend on `services/` and `contracts/`, not `backend.api`.
- Web-to-worker communication goes through `AbstractTaskDispatcher`.
- Dispatch worker tasks through `task_dispatcher.enqueue_*()`, never `.kiq()` directly from web code.
- `scripts/check_import_boundaries.py` enforces this split.

## Dependency Injection

- `api/deps/` provides DI factories.
- Do not import worker tasks or worker modules in the web layer.
- Services receive dependencies through `__init__`, not global singletons.
- `AbstractUnitOfWork` wraps transactions and repositories.
- Repository methods receive `session` as an explicit parameter.

## Application Layer

- `backend/application/` holds workflows grouped by process boundary (chat, knowledge, repo_analysis).
- Web-side workflows are injected through `api/deps/workflows.py`; worker-side workflows are called from `worker/tasks/*`.
- A workflow composes services and may also use `AbstractUnitOfWork` repositories directly for persistence steps (see `application/chat/web_stream_workflow.py`); the call chain becomes endpoint -> (application workflow) -> service / repository.
- Workflows follow the same import rules as their host process: web-side workflows must not import `backend.worker`.

## 3-Tier Call Chain

```text
HTTP endpoint -> Service -> Repository -> ORM Model
```

- Endpoints own HTTP concerns only.
- Services own business logic.
- Repositories own SQLAlchemy queries.
- Do not query ORM models directly from endpoints.
