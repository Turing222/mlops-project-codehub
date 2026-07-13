# Quality Gates

Always prefix Python commands with `uv run` (backend; frontend commands go through `make frontend-*`).

## Recommended Pipelines

```bash
make flow-fast
make flow-ci
make flow-pr-preflight
```

- `make flow-fast` is the default local monorepo check: backend static/unit/component checks plus `make frontend-check` (includes `qa-standards-fast`).
- `make flow-ci` is the PR baseline: `flow-fast`, CI-safe backend integration tests, and frontend mock e2e.
- `make flow-pr-preflight` mirrors `static-ci` + `pr-gate-ci` without Docker smoke; needs local Postgres and Redis.

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
make frontend-test-coverage
make frontend-build
make frontend-e2e-mock
make frontend-check
```

## Semantic Navigation MCP

Project-scoped Serena MCP config is available for Codex and Claude Code.
It is a navigation layer only; keep edits, shell commands, and validation in the
host agent workflow.

```bash
# verify Serena can index Python and TypeScript symbols
serena project index

# verify the stdio server starts; it exits when stdin closes
scripts/dev/serena-mcp.sh codex
scripts/dev/serena-mcp.sh claude-code
```

- Codex reads `.codex/config.toml` after the project is trusted.
- Claude Code reads `.mcp.json` at session start; approve the project-scoped server when prompted.
- No manual server startup is needed for stdio mode. The client starts Serena as a subprocess.
- Exposed tools are restricted to the `initial_instructions` bootstrap manual plus symbol overview, symbol search, declaration, references, and file diagnostics.
- Serena uses LSP for `python` and `typescript`; TypeScript uses the project app's `typescript-language-server`.

## Operational Constraints

- Do not modify code or files unless the user explicitly asks for implementation, code changes, or file edits.
- Keep generated write chunks under 150 lines per tool call.
- Cap noisy command output with `| head -200`.
- Do not browse localhost; use `curl` for health checks.
- Check Docker status with `docker compose ps`.
- Inspect Docker failures with `docker compose logs --tail=50 <svc>`.
