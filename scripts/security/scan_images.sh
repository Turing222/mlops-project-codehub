#!/usr/bin/env bash
# ============================================================================
# Docker image security scan (mirrors security-ci.yml backend-images +
# frontend-image).
#
# Requires: docker daemon, trivy on PATH.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

cd "$PROJECT_ROOT"

TRIVY_SEVERITY="${TRIVY_SEVERITY:-HIGH,CRITICAL}"
BACKEND_WEB_IMAGE="${BACKEND_WEB_IMAGE:-dewflow-backend:security-web}"
BACKEND_WORKER_IMAGE="${BACKEND_WORKER_IMAGE:-dewflow-backend:security-worker}"
FRONTEND_IMAGE="${FRONTEND_IMAGE:-dewflow-frontend:security}"

require_command() {
    local cmd="$1"
    local hint="$2"

    if ! command -v "$cmd" >/dev/null 2>&1; then
        log_error "$cmd is required for image security scans"
        log_error "$hint"
        exit 1
    fi
}

scan_image() {
    local image_ref="$1"
    local label="$2"

    log_section "Scanning $label ($image_ref)"
    trivy image \
        --severity "$TRIVY_SEVERITY" \
        --ignore-unfixed \
        --format table \
        --exit-code 1 \
        "$image_ref"
}

require_command docker "Start Docker and retry."
require_command trivy "Install Trivy, e.g. sudo apt-get install trivy (see security-ci.yml)."

if ! docker info >/dev/null 2>&1; then
    log_error "Docker daemon is not reachable"
    exit 1
fi

log_section "Building backend web image"
docker build --target web -t "$BACKEND_WEB_IMAGE" .
scan_image "$BACKEND_WEB_IMAGE" "backend web image"

log_section "Building backend worker image"
docker build --target worker -t "$BACKEND_WORKER_IMAGE" .
scan_image "$BACKEND_WORKER_IMAGE" "backend worker image"

log_section "Building frontend fallback image"
docker build -f frontend/apps/admin/Dockerfile -t "$FRONTEND_IMAGE" .
scan_image "$FRONTEND_IMAGE" "frontend fallback image"

log_section "Image security scan passed"
