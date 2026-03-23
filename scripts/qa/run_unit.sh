#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

log_section "Running unit tests"

if (( $# == 0 )); then
    set -- tests/unit
fi

uv run pytest "$@"
