#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

require_cmd docker

# Superseded infra tags and ephemeral local validation images only.
# App release images (dewflow-backend:* / dewflow-frontend:*) are intentionally
# excluded so locally built tags remain available until manually removed.
STALE_IMAGES=(
    nginx:1.27-alpine
    nginx:1.27.5-bookworm
    redis:7.4-alpine
    pgvector/pgvector:0.8.1-pg17-bookworm
    quay.io/minio/minio:latest
    quay.io/minio/mc:latest
    dewflow-frontend:analyze
    dewflow-frontend:nginx-upgrade
    dewflow-frontend:2.0.0
    dewflow-backend:cache-web-check
    dewflow-backend:cache-worker-check
    ci-validate-ai:0
    ci-validate-ai:0-scheduler
)

log_section "Removing superseded infra and ephemeral images"

removed=0
skipped=0
for image_ref in "${STALE_IMAGES[@]}"; do
    if docker image inspect "$image_ref" >/dev/null 2>&1; then
        docker rmi "$image_ref" >/dev/null
        log_info "Removed $image_ref"
        removed=$((removed + 1))
    else
        skipped=$((skipped + 1))
    fi
done

log_info "Removed $removed image(s); $skipped not present locally"
docker image prune -f >/dev/null
log_info "Pruned dangling image layers"
