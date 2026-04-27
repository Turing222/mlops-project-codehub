#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker

log_section "Starting smoke environment"
ensure_smoke_required_secrets
ensure_smoke_volumes
compose_smoke up -d
compose_smoke ps
