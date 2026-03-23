#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

log_section "Running lint"
uv run ruff check .

log_section "Running typecheck"
uv run ty check .
