# Smoke Environment Secrets

This directory contains auto-generated and user-configured secrets for the local compose (`smoke`) environment.

## ⚠️ Security Notice
- **NEVER** commit any files in this directory except for this `README.md` and `.gitkeep`.
- All `.txt` files containing actual API keys or passwords are automatically ignored by Git.

## How to Set API Keys

Do not manually edit files in this directory. Use the provided automated command to securely set your API keys without exposing them to your shell history:

```bash
# Example: Testing with Bifrost gateway (default)
make set-llm PROVIDER=bifrost

# Example: Testing with Gemini (direct connect)
make set-llm PROVIDER=gemini

# Example: Fallback to Mock
make set-llm PROVIDER=mock
```

The script will prompt you for the key, save it atomically to `secrets/smoke/<provider>_api_key.txt` with `600` permissions, and automatically update your `.env.smoke` configuration.

## Bifrost Gateway

Bifrost runs as an optional profile in `docker-compose.db.yml`. Start it with
`docker compose --profile bifrost up`. It requires `BIFROST_API_KEY` (set via
`make set-llm PROVIDER=bifrost`) and `BIFROST_ENCRYPTION_KEY` (set in
`.env.smoke`). The Dewflow API and worker read `BIFROST_API_KEY_FILE` via
Docker secrets. Bifrost reads `DEEPSEEK_API_KEY` from the Docker secret via
entrypoint, keeping a single configuration source.

When using Bifrost virtual-key governance, `BIFROST_API_KEY` must start with
`sk-bf-`; Bifrost v1.4.11 replaces non-matching values during bootstrap.
