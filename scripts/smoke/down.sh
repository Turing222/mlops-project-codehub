#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker

log_section "Stopping smoke environment"

args=(down)
if [[ "${SMOKE_DOWN_VOLUMES:-false}" == "true" ]]; then
    args+=(-v)
fi

compose_smoke "${args[@]}"

if [[ "${SMOKE_DOWN_VOLUMES:-false}" == "true" ]]; then
    for volume_name in "${SMOKE_REQUIRED_VOLUME_NAMES[@]}"; do
        docker volume rm "$volume_name" >/dev/null 2>&1 || true
    done
fi
