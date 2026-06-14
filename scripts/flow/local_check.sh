#!/usr/bin/env bash
# ============================================================================
# Local verification flow with per-step log artifacts.
#
# Runs the same pipeline as `make flow-local`, writing stdout/stderr for each
# step under logs/flow-local/<run-id>-<step>.log and aggregating likely
# errors/warnings into <run-id>-issues.txt.
#
# Usage:
#   make flow-local
#   FLOW_LOG_DIR=/tmp/my-logs make flow-local
#   FLOW_COLLECT_SMOKE_LOGS=false make flow-local
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

cd "$PROJECT_ROOT"

FLOW_LOG_DIR="${FLOW_LOG_DIR:-${PROJECT_ROOT}/logs/flow-local}"
FLOW_COLLECT_SMOKE_LOGS="${FLOW_COLLECT_SMOKE_LOGS:-true}"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
FAILED_STEP=""

mkdir -p "$FLOW_LOG_DIR"
printf '%s\n' "$RUN_ID" >"$FLOW_LOG_DIR/latest-run-id.txt"

log_section() {
    printf '\n==> %s\n' "$1"
}

run_step() {
    local name="$1"
    shift
    local log_file="$FLOW_LOG_DIR/$RUN_ID-$name.log"
    local exit_code=0

    log_section "Step: $name"
    log_info "Logging to: $log_file"

    set +e
    "$@" 2>&1 | tee "$log_file"
    exit_code="${PIPESTATUS[0]}"
    set -e

    if ((exit_code != 0)); then
        FAILED_STEP="$name"
        return "$exit_code"
    fi

    log_info "Step '$name' passed"
    return 0
}

collect_issues() {
    local issues_file="$FLOW_LOG_DIR/$RUN_ID-issues.txt"
    local -a patterns=(
        'error'
        'warn'
        'warning'
        '\(!\)'
        'FAIL'
        'failed'
        '\[ERROR\]'
        '\[WARN\]'
    )
    local pattern
    local joined_pattern=""

    for pattern in "${patterns[@]}"; do
        if [[ -n "$joined_pattern" ]]; then
            joined_pattern+='|'
        fi
        joined_pattern+="$pattern"
    done

    grep -hiE "$joined_pattern" "$FLOW_LOG_DIR/$RUN_ID-"*.log 2>/dev/null \
        | sort -u >"$issues_file" || true

    if [[ -s "$issues_file" ]]; then
        log_warn "Issues summary: $issues_file"
    else
        log_info "No error/warning lines matched; issues file not created"
        rm -f "$issues_file"
    fi
}

write_manifest() {
    local manifest_file="$FLOW_LOG_DIR/$RUN_ID-manifest.txt"

    {
        printf 'run_id=%s\n' "$RUN_ID"
        printf 'started_at=%s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
        printf 'log_dir=%s\n' "$FLOW_LOG_DIR"
        if [[ -n "$FAILED_STEP" ]]; then
            printf 'failed_step=%s\n' "$FAILED_STEP"
            printf 'status=failed\n'
        else
            printf 'status=passed\n'
        fi
        printf '\nartifacts:\n'
        ls -1 "$FLOW_LOG_DIR/$RUN_ID-"* 2>/dev/null || true
    } >"$manifest_file"

    log_info "Run manifest: $manifest_file"
}

on_failure() {
    collect_issues
    write_manifest

    if [[ "$FLOW_COLLECT_SMOKE_LOGS" == "true" ]]; then
        log_warn "Collecting smoke container logs after failure"
        make env-smoke-logs || true
    fi

    log_error "flow-local failed at step '$FAILED_STEP'"
    log_error "Artifacts directory: $FLOW_LOG_DIR (run id: $RUN_ID)"
    if [[ -f "$FLOW_LOG_DIR/$RUN_ID-issues.txt" ]]; then
        log_error "Issues summary: $FLOW_LOG_DIR/$RUN_ID-issues.txt"
    fi
    log_error "Failed step log: $FLOW_LOG_DIR/$RUN_ID-$FAILED_STEP.log"
}

read -r -a pytest_extra <<<"${PYTEST_ARGS:-}"

log_section "Running local verification flow (run id: $RUN_ID)"

smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"
if [[ ! -f "$smoke_env_path" ]]; then
    log_info "Smoke env file not found, generating it from the shared template"
    make env-smoke-prepare
fi

if ! run_step image-build make image-build; then on_failure; exit 1; fi
if ! run_step flow-fast make flow-fast; then on_failure; exit 1; fi
if ! run_step smoke-up make env-smoke-up; then on_failure; exit 1; fi
if ! run_step smoke-wait make env-smoke-wait; then on_failure; exit 1; fi
if ! run_step seed-dev bash scripts/qa/run_with_smoke_env.sh make seed-dev; then on_failure; exit 1; fi
if ! run_step integration \
    bash scripts/qa/run_with_smoke_env.sh uv run pytest \
        -m "not performance and not requires_llm" \
        "${pytest_extra[@]}"; then
    on_failure
    exit 1
fi
if ! run_step e2e-smoke make frontend-e2e-smoke; then on_failure; exit 1; fi

collect_issues
write_manifest

log_section "Local verification passed"
log_info "Artifacts directory: $FLOW_LOG_DIR (run id: $RUN_ID)"
if [[ -f "$FLOW_LOG_DIR/$RUN_ID-issues.txt" ]]; then
    log_warn "Non-fatal warnings captured in: $FLOW_LOG_DIR/$RUN_ID-issues.txt"
fi
