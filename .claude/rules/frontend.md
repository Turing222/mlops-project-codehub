---
paths:
  - "frontend/**"
---

# Frontend Rules

Distilled from `.codex/skills/project/references/frontend.md` and `frontend/docs/`.

App: `frontend/apps/admin` (pnpm workspace). React 19 + TS + Vite + antd 6 +
TanStack Query 5 + Zustand 5 + zod 4.

## Layering

- `pages/` compose route-level only; business logic sinks into `features/*`.
  No raw requests in pages.
- API calls go through `src/api/` (one module per backend domain); request/response
  validated by zod schemas in `schemas/`; http client/error/trace in `lib/`.
- SSE / chunk stream parsing is centralized in `streams/`.
- State: Zustand (`stores/`) for client state, TanStack Query for server state,
  local state for component-only.

## Contracts

- Backend owns business truth; validate responses at runtime.
- No auto-retry for non-idempotent POST.
- Feature flags only via `useFeatureFlag()` / `FeatureGate`; never connect to
  GrowthBook directly.

## Validate (pnpm only)

- `make frontend-lint`, `frontend-typecheck`, `frontend-test`, `frontend-build`,
  `make frontend-check`. Bundle: `make frontend-bundle-check`.

Full rules: frontend.md + `frontend/docs/standards/`.
