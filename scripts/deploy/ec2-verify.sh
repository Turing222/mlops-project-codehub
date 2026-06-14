#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd curl
require_cmd uv
require_deploy_env_file
load_deploy_env

log_section "Running EC2 deploy smoke verification"

export SMOKE_BASE_URL="${DEPLOY_BASE_URL}"
export SMOKE_LIVE_PATH="${DEPLOY_API_LIVE_PATH}"
export SMOKE_READY_PATH="${DEPLOY_API_READY_PATH}"
export SMOKE_PYTEST_TARGETS="${DEPLOY_SMOKE_PYTEST_TARGETS}"
export SMOKE_PRINT_STACK_STATUS=false

bash scripts/smoke/test.sh
