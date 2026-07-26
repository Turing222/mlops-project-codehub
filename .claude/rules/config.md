---
paths:
  - "deploy/**"
  - "**/*.yml"
  - "**/*.yaml"
  - "**/Dockerfile*"
---

# Config & Compose Rules

Distilled from `.codex/skills/project/references/` (config-policy.md,
secrets-and-flags.md).

## Comments

- Keep config/compose fields uncommented unless a value is surprising. A one-line
  comment is acceptable; a paragraph is not.

## Config vs code

- Zero code/test change to adjust -> config. Changes algorithm semantics -> code.
- Tuning knobs / env-specific / ops thresholds -> config (`AISettings` for 1-3
  related params, else YAML + Pydantic schema).
- Algorithm details (regex, char sets, tokenization) -> module-level constants.

## Secrets (never commit real secret values)

- Sensitive runtime values support `FOO_FILE`. A new secret `FOO` is wired through
  `backend/core/secret_env.py` and `docker-compose.db.yml` (full checklist in
  secrets-and-flags.md).
- Non-sensitive toggles -> `.env.smoke.template` + Pydantic settings.

## Validate

- Smoke / db compose (`docker-compose.db.yml`): provide placeholder image vars,
  then run `docker compose --env-file .env.smoke -f docker-compose.db.yml config
  --quiet` (requires `DOCKER_IMAGE_NAME_WEB` and `DOCKER_IMAGE_NAME_AI`).
- Deploy compose (`deploy/docker-compose.yml` and `deploy/*.yml`):
  `make deploy-ec2-check` (validates env + compose config; local rehearsal:
  `make deploy-local-prod-check`). These wire `DOCKER_IMAGE_NAME_*` and the deploy
  env file; a bare `docker compose config` fails on the required image vars.

Full rationale: config-policy.md, secrets-and-flags.md.
