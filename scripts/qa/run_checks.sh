#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

log_section "Running lint"
uv run ruff check .

log_section "Running import boundary check"
uv run python scripts/check_import_boundaries.py

log_section "Checking for bare while True loops"
uv run python scripts/qa/check_no_while_true.py

log_section "Running test marker audit"
uv run python scripts/qa/check_test_markers.py

log_section "Running typecheck"
uv run ty check .

log_section "Running Alembic migration check"
bash scripts/qa/alembic_check.sh

log_section "Running config/env check"
uv run python scripts/qa/config_check.py
