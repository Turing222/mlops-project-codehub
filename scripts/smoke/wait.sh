#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

log_section "Waiting for smoke environment"

if ! wait_for_http_ok "${SMOKE_BASE_URL}${SMOKE_LIVE_PATH}"; then
    print_smoke_logs
    exit 1
fi

log_info "Smoke live endpoint is reachable"
