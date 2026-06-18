# Secrets And Feature Flags

Use this reference when adding or changing API keys, secret files, environment keys, Docker secrets, smoke configuration, or feature flags.

## Secret Standard

All sensitive runtime values must support `FOO_FILE`.

For a new secret named `FOO`:

- Add `FOO` to `backend/core/secret_env.py`.
- Add `FOO` to the app secret list in `docker-compose.db.yml`.
- Add `FOO_FILE: /run/secrets/FOO` to `x-secret-file-env` in `docker-compose.db.yml`.
- Add a `secrets:` entry mapping `FOO` to `${SMOKE_FOO_FILE:-./secrets/smoke/foo.txt}`.
- Add `SMOKE_FOO_FILE=./secrets/smoke/foo.txt` to `.env.smoke.template`.
- Add `ensure_smoke_secret_file "SMOKE_FOO_FILE" "./secrets/smoke/foo.txt" "empty"` to `scripts/lib/common.sh`.
- Add or update `tests/unit/core/test_config.py` to prove `FOO_FILE` is loaded into settings.

Do not commit real files under `secrets/smoke/`. Those files are local smoke secrets and are ignored.

## Config Placement

- Secret values: `FOO_FILE` or runtime secret manager, never committed env files.
- Non-sensitive environment toggles: `.env.smoke.template` and Pydantic settings.
- Complex non-sensitive provider definitions: YAML under `configs/` with schema validation.
- Code constants: only algorithm details that should change with code and tests.

## GrowthBook Feature Flags

Feature flags are controlled by the backend. Frontend code must not connect to GrowthBook directly.

For a new flag:

- Create the boolean feature in GrowthBook using a stable `kebab-case` key.
- Register the key in `FeatureFlagService` with explicit scope and fallback.
- Use `/api/v1/auth/config` for anonymous/system flags.
- Use the `features` field from the `/api/v1/users/me` response for logged-in user flags.
- Consume frontend flags only through `useFeatureFlag()` or `FeatureGate`.
- Add `tests/unit/services/test_feature_flag_service.py` coverage for missing-key fallback and SDK evaluation when the key exists.

Each flag should have a known owner, fallback, scope (`system` or `user`), and consuming UI/backend surface.

## Validation

For secret or smoke config changes:

```bash
bash -n scripts/lib/common.sh
DOCKER_IMAGE_NAME_WEB=dewflow-backend:local-web \
  DOCKER_IMAGE_NAME_AI=dewflow-backend:local-ai \
  docker compose --env-file .env.smoke -f docker-compose.db.yml config --quiet
uv run pytest tests/unit/core/test_config.py -q
```

For feature flag changes:

```bash
uv run pytest tests/unit/services/test_feature_flag_service.py -q
```
