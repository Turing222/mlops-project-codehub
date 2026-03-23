#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOCKER_IMAGE_NAME="${DOCKER_IMAGE_NAME:-ai-tutor-backend:v1}"
SMOKE_COMPOSE_FILE="${SMOKE_COMPOSE_FILE:-docker-compose.db.yml}"
SMOKE_BASE_URL="${SMOKE_BASE_URL:-http://localhost:8000}"
SMOKE_LIVE_PATH="${SMOKE_LIVE_PATH:-/api/v1/health_check/live}"
SMOKE_READY_PATH="${SMOKE_READY_PATH:-/api/v1/health_check/db_ready}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-120}"
SMOKE_POLL_INTERVAL_SECONDS="${SMOKE_POLL_INTERVAL_SECONDS:-2}"

log_section() {
    printf '\n==> %s\n' "$1"
}

log_info() {
    printf '[INFO] %s\n' "$1"
}

log_warn() {
    printf '[WARN] %s\n' "$1"
}

log_error() {
    printf '[ERROR] %s\n' "$1" >&2
}

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        log_error "Missing required command: $1"
        exit 1
    fi
}

compose_smoke() {
    docker compose -f "$SMOKE_COMPOSE_FILE" "$@"
}

print_smoke_logs() {
    log_warn "Smoke environment status:"
    compose_smoke ps || true
    log_warn "Recent Smoke logs:"
    compose_smoke logs --tail=200 || true
}

wait_for_http_ok() {
    local url="$1"
    local timeout="${2:-$SMOKE_TIMEOUT_SECONDS}"
    local interval="${3:-$SMOKE_POLL_INTERVAL_SECONDS}"
    local elapsed=0
    local status

    require_cmd curl

    while (( elapsed < timeout )); do
        status="$(curl -sS -o /dev/null -w '%{http_code}' "$url" || true)"
        if [[ "$status" == "200" ]]; then
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    log_error "Timed out waiting for HTTP 200: $url"
    return 1
}
