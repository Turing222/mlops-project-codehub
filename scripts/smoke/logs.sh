#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker
require_smoke_env_file

SMOKE_LOG_DIR="${SMOKE_LOG_DIR:-${PROJECT_ROOT}/logs/smoke}"
SMOKE_LOG_TAIL="${SMOKE_LOG_TAIL:-200}"
mkdir -p "$SMOKE_LOG_DIR"

log_section "Collecting smoke environment logs"

{
    log_warn "Smoke environment status:"
    compose_smoke ps || true
} 2>&1 | tee "$SMOKE_LOG_DIR/compose-ps.txt"

{
    log_warn "Recent smoke logs:"
    compose_smoke logs --tail="$SMOKE_LOG_TAIL" || true
} 2>&1 | tee "$SMOKE_LOG_DIR/compose-logs.txt"

log_info "Smoke log artifacts written to $SMOKE_LOG_DIR"
