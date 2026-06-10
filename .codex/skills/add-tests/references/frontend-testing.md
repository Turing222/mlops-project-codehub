# Frontend Testing Reference

Use this reference when adding or updating tests under `frontend/apps/admin`.
`frontend/docs/standards/testing.md` is the source of truth; this file is the routing summary.

## Layer Selection

- Vitest unit: schema parse, request helpers, store actions, route smoke, pure utilities.
- Vitest integration (jsdom + MSW): query hooks, mutation invalidation, token bootstrap, unauthorized cleanup, stream parser.
- Playwright mock e2e: user-visible flows against mocked API routes (`page.route`).
- Playwright smoke e2e: real backend; needs `E2E_SMOKE_USER` / `E2E_SMOKE_PASS` and is not a default PR gate.

Prefer the lowest layer that proves the behavior.

## Placement And Mock Data

- Vitest tests co-locate with sources: `src/**/*.test.ts(x)`.
- Playwright tests live in `e2e/tests/` with config at `e2e/playwright.config.ts`.
- Vitest/MSW and Playwright mock e2e share base responses from `src/test/mock-data`; do not fork mock payloads.

## Minimum Coverage For New Features

Follow the "新增功能的最低测试建议" section in `frontend/docs/standards/testing.md`:
new API -> schema or helper test; new query -> key, enabled condition, invalidation;
new form -> key validation and submit payload; new stream logic -> chunk parser, error event, done event, abort.

## Verification

```bash
make frontend-test
make frontend-e2e-mock
E2E_SMOKE_USER=... E2E_SMOKE_PASS=... make frontend-e2e-smoke
```
