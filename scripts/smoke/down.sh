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
