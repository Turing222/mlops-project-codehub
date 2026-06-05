#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd curl
require_cmd docker
require_cmd uv

log_section "Verifying smoke environment"

if [[ "${SMOKE_PRINT_STACK_STATUS:-true}" == "true" ]]; then
    compose_smoke ps
fi

if ! wait_for_http_ok "${SMOKE_BASE_URL}${SMOKE_LIVE_PATH}"; then
    if [[ "${SMOKE_PRINT_STACK_STATUS:-true}" == "true" ]]; then
        print_smoke_logs
    fi
    exit 1
fi

if ! wait_for_http_ok "${SMOKE_BASE_URL}${SMOKE_READY_PATH}"; then
    if [[ "${SMOKE_PRINT_STACK_STATUS:-true}" == "true" ]]; then
        print_smoke_logs
    fi
    exit 1
fi

log_info "Liveness response:"
curl -fsS "${SMOKE_BASE_URL}${SMOKE_LIVE_PATH}"
printf '\n'

log_info "Database readiness response:"
curl -fsS "${SMOKE_BASE_URL}${SMOKE_READY_PATH}"
printf '\n'

log_section "Running smoke pytest checks"

if [[ -z "${SMOKE_STRICT:-}" ]]; then
    if [[ "${CI:-}" == "true" || "${GITHUB_ACTIONS:-}" == "true" ]]; then
        export SMOKE_STRICT=true
    else
        export SMOKE_STRICT=false
    fi
else
    export SMOKE_STRICT
fi

read -r -a smoke_pytest_args <<<"${SMOKE_PYTEST_ARGS}"
read -r -a smoke_pytest_targets <<<"${SMOKE_PYTEST_TARGETS}"

SMOKE_LOG_DIR="${SMOKE_LOG_DIR:-${PROJECT_ROOT}/logs/smoke}"
mkdir -p "$SMOKE_LOG_DIR"
SMOKE_LOG_FILE="${SMOKE_LOG_DIR}/pytest-$(date +%Y%m%d-%H%M%S).log"

# Run pytest: full output goes to log file, terminal only shows progress + summary
pytest_exit=0
uv run pytest \
    "${smoke_pytest_args[@]}" \
    "${smoke_pytest_targets[@]}" \
    --no-header \
    -q \
    --tb=short \
    -p no:logging \
    >"$SMOKE_LOG_FILE" 2>&1 || pytest_exit=$?

# Extract just the one-line progress line (e.g. "FFFFFFF  [100%]")
grep -E '^\S+\s+\[\d+%\]' "$SMOKE_LOG_FILE" || true

# Always show the short summary section (FAILED/passed counts)
sed -n '/^=.*short test summary/,/^=.*=/p' "$SMOKE_LOG_FILE" || true
# Also show the final results line like "7 failed"
tail -1 "$SMOKE_LOG_FILE" | grep -E 'failed|passed|error|warning' || true

if [[ "$pytest_exit" -ne 0 ]]; then
    log_error "Smoke tests failed (exit $pytest_exit). Full log: $SMOKE_LOG_FILE"
    log_error "Run:  cat $SMOKE_LOG_FILE  to see full traceback"
    log_error "Run:  make env-smoke-logs  to see container logs"
    exit "$pytest_exit"
fi

log_info "Smoke tests passed. Full log: $SMOKE_LOG_FILE"
