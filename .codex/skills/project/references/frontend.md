# Frontend Context

Use this reference for any work under `frontend/`. Detailed rules live in `frontend/docs/`; this file is only the routing index.

## Overview

The frontend is a pnpm workspace with a single app: `frontend/apps/admin`.

- Stack: React 19, TypeScript, Vite 7, antd 6, TanStack Query 5, Zustand 5, react-router 7, zod 4.
- Testing: Vitest + Testing Library + MSW for unit/integration, Playwright for e2e (mock and smoke projects).
- Feature flags are served by the backend; the frontend never connects to GrowthBook directly (see [secrets-and-flags.md](secrets-and-flags.md)).

## Directory Map

```text
frontend/apps/admin/
  src/
    api/         API helpers, one module per backend domain
    schemas/     zod request/response schemas
    lib/         http client, error normalization, trace, idempotency
    features/    business capabilities (components + hooks per feature)
    pages/       route-level composition only
    components/  shared presentational components
    stores/      Zustand client state
    streams/     SSE / chunk stream protocol parsing
    query/       TanStack Query setup and shared keys
    context/     React context providers
    test/        test setup and shared mock data (test/mock-data)
    utils/ types/ assets/
  e2e/           Playwright config and tests
frontend/docs/   architecture and standards (source of truth)
```

## Standards Index

Read the smallest matching document before frontend work:

- [frontend/docs/architecture.md](../../../../frontend/docs/architecture.md): core principles (backend owns business truth, runtime validation, state layering, no raw requests in pages, no auto-retry for non-idempotent POST) plus network, token lifecycle, idempotency, retry, and query rules.
- [frontend/docs/standards/api.md](../../../../frontend/docs/standards/api.md): steps for adding an API (schema -> api helper -> query).
- [frontend/docs/standards/components.md](../../../../frontend/docs/standards/components.md): pages compose only; business logic sinks into `features/*`.
- [frontend/docs/standards/state.md](../../../../frontend/docs/standards/state.md): Zustand vs TanStack Query vs local component state boundaries.
- [frontend/docs/standards/streaming.md](../../../../frontend/docs/standards/streaming.md): SSE parsing centralized in `streams/`.
- [frontend/docs/standards/styling.md](../../../../frontend/docs/standards/styling.md): antd first, localized styles.
- [frontend/docs/standards/testing.md](../../../../frontend/docs/standards/testing.md): test layering and minimum-test guidance for new features.

## Validation

Use Make targets from the repository root:

```bash
make frontend-lint
make frontend-typecheck
make frontend-test
make frontend-build
make frontend-e2e-mock
make frontend-check
```

Smoke e2e runs against a real backend, needs `E2E_SMOKE_USER` / `E2E_SMOKE_PASS`, and is not a default PR gate:

```bash
E2E_SMOKE_USER=... E2E_SMOKE_PASS=... make frontend-e2e-smoke
```
