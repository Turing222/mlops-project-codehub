# Quality Gates

Always prefix Python commands with `uv run` (backend; frontend commands go through `make frontend-*`).

## Recommended Pipelines

```bash
make flow-fast
make flow-ci
```

- `make flow-fast` is the default local monorepo check: backend static/unit/component checks plus `make frontend-check`.
- `make flow-ci` is the PR baseline: `flow-fast`, CI-safe backend integration tests, and frontend mock e2e.

## Backend Compatibility Aliases

These aliases are backend-only and do not run frontend checks:

```bash
make lint       # qa-lint
make typecheck  # qa-typecheck
make test       # qa-test-all
make check      # flow-static
```

## Focused Targets

```bash
make qa-lint
make qa-format
make qa-typecheck
make qa-boundaries
make qa-layer-deps
make qa-no-while-true
make qa-alembic-check
make qa-config-check
make qa-test-markers
make qa-test-unit
make qa-test-component
make qa-test-integration
make qa-test-all
make qa-skill-check
make qa-standards-fast
```

## Frontend Targets

```bash
make frontend-lint
make frontend-typecheck
make frontend-test
make frontend-build
make frontend-e2e-mock
make frontend-check
```

## Operational Constraints

- Do not modify code or files unless the user explicitly asks for implementation, code changes, or file edits.
- Keep generated write chunks under 150 lines per tool call.
- Cap noisy command output with `| head -200`.
- Do not browse localhost; use `curl` for health checks.
- Check Docker status with `docker compose ps`.
- Inspect Docker failures with `docker compose logs --tail=50 <svc>`.
