#!/usr/bin/env bash
# ============================================================================
# Dependency security scan (mirrors security-ci.yml python-dependencies +
# frontend-dependencies).
#
# - Python production deps: strict (exit 1 on findings)
# - Python dev deps: report only (matches CI continue-on-error)
# - Frontend prod: high+; dev: critical+
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

cd "$PROJECT_ROOT"

SECURITY_TMP_DIR="${SECURITY_TMP_DIR:-.tmp/security}"
PROD_REQUIREMENTS="$SECURITY_TMP_DIR/requirements.txt"
DEV_REQUIREMENTS="$SECURITY_TMP_DIR/requirements-dev.txt"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org}"

mkdir -p "$SECURITY_TMP_DIR"

if ! command -v uv >/dev/null 2>&1; then
    log_error "uv is required for dependency security scans"
    exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
    log_error "pnpm is required for frontend dependency security scans"
    exit 1
fi

log_section "Exporting locked Python production dependencies"
uv export \
    --frozen \
    --all-extras \
    --no-default-groups \
    --no-emit-project \
    --no-emit-workspace \
    --no-hashes \
    --format requirements.txt \
    --output-file "$PROD_REQUIREMENTS" \
    >/dev/null

log_section "Auditing Python production dependencies (strict)"
uvx pip-audit \
    --requirement "$PROD_REQUIREMENTS" \
    --strict \
    --progress-spinner off \
    --desc \
    --aliases

log_section "Exporting locked Python dev dependencies"
uv export \
    --frozen \
    --only-group dev \
    --no-emit-project \
    --no-emit-workspace \
    --no-hashes \
    --format requirements.txt \
    --output-file "$DEV_REQUIREMENTS" \
    >/dev/null

log_section "Auditing Python dev dependencies (report only)"
set +e
uvx pip-audit \
    --requirement "$DEV_REQUIREMENTS" \
    --strict \
    --progress-spinner off \
    --desc \
    --aliases
dev_audit_status=$?
set -e
if ((dev_audit_status != 0)); then
    log_warn "Python dev dependency audit found issues (non-blocking; mirrors CI continue-on-error)"
fi

log_section "Auditing frontend production dependencies (high+)"
pnpm --dir frontend audit --prod --audit-level high --registry "$NPM_REGISTRY"

log_section "Auditing frontend dev dependencies (critical+)"
pnpm --dir frontend audit --dev --audit-level critical --registry "$NPM_REGISTRY"

log_section "Dependency security scan passed"
