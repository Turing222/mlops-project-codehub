#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

log_section "Running integration tests"

if (( $# == 0 )); then
    set -- tests/integration
fi

uv run pytest "$@"
