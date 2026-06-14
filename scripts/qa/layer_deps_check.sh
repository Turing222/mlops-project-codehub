#!/usr/bin/env bash
# Verify each extras group resolves the packages it should (and not those it shouldn't).
# Uses uv export (dependency resolution only, no install) — fast and CI-safe.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

_failures=0

export_for_extras() {
    local args=()
    local extra
    for extra in "$@"; do
        args+=(--extra "$extra")
    done
    uv export --no-dev "${args[@]}" 2>/dev/null
}

check_has() {
    local layer="$1" extra="$2" pkg="$3"
    shift 3
    # Use command substitution instead of pipe to avoid SIGPIPE + pipefail issues
    if [[ -n "$(export_for_extras "$extra" "$@" | grep "^${pkg}==" || true)" ]]; then
        printf "  ${GREEN}[+]${NC} %s has %s\n" "$layer" "$pkg"
    else
        printf "  ${RED}[-]${NC} %s MISSING %s (extra=%s)\n" "$layer" "$pkg" "$extra"
        _failures=$((_failures + 1))
    fi
}

check_not_has() {
    local layer="$1" extra="$2" pkg="$3"
    shift 3
    if [[ -n "$(export_for_extras "$extra" "$@" | grep "^${pkg}==" || true)" ]]; then
        printf "  ${RED}[-]${NC} %s HAS %s (should be in other extra)\n" "$layer" "$pkg"
        _failures=$((_failures + 1))
    else
        printf "  ${GREEN}[+]${NC} %s correctly missing %s\n" "$layer" "$pkg"
    fi
}

check_ai_worker_imports() {
    if DEBUG=false uv run --no-dev --extra ai --extra worker python -c "import backend.worker.tasks.llm_tasks; import backend.worker.tasks.knowledge_tasks; import backend.worker.tasks.repo_analysis_tasks" >/dev/null 2>&1; then
        printf "  ${GREEN}[+]${NC} ai+worker imports worker task modules without web extras\n"
    else
        printf "  ${RED}[-]${NC} ai+worker cannot import worker task modules without web extras\n"
        _failures=$((_failures + 1))
    fi
}

echo "==> Checking web extras (extra=web)"
check_has     "web" "web" "fastapi"
check_has     "web" "web" "uvicorn"
check_not_has "web" "web" "pypdfium2"
check_not_has "web" "web" "taskiq"
check_not_has "web" "web" "taskiq-redis"
echo ""

echo "==> Checking ai extras (extra=ai)"
check_has     "ai" "ai" "openai"
check_not_has "ai" "ai" "fastapi"
check_not_has "ai" "ai" "taskiq"
check_not_has "ai" "ai" "taskiq-redis"
echo ""

echo "==> Checking worker extras (extra=ai+worker)"
check_has     "ai+worker" "ai" "taskiq" "worker"
check_has     "ai+worker" "ai" "taskiq-redis" "worker"
check_ai_worker_imports
echo ""

if (( _failures == 0 )); then
    echo "All layer deps OK."
    exit 0
else
    echo "$_failures layer dep violation(s) found."
    exit 1
fi
