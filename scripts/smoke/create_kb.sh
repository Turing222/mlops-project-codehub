#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_smoke_env_file

smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"

set -a
source "$smoke_env_path"
set +a

exec .venv/bin/python scripts/smoke/create_kb.py "$@"
