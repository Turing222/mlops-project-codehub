#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd curl
require_cmd docker

log_section "Verifying smoke environment"
compose_smoke ps

if ! wait_for_http_ok "${SMOKE_BASE_URL}${SMOKE_LIVE_PATH}"; then
    print_smoke_logs
    exit 1
fi

if ! wait_for_http_ok "${SMOKE_BASE_URL}${SMOKE_READY_PATH}"; then
    print_smoke_logs
    exit 1
fi

log_info "Liveness response:"
curl -fsS "${SMOKE_BASE_URL}${SMOKE_LIVE_PATH}"
printf '\n'

log_info "Database readiness response:"
curl -fsS "${SMOKE_BASE_URL}${SMOKE_READY_PATH}"
printf '\n'
