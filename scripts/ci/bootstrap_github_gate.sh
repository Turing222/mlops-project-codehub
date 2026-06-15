#!/usr/bin/env bash
# ============================================================================
# Bootstrap GitHub repository settings for CI gate P0 / P1.
#
# P0: repository secrets + variables used by frontend-e2e-smoke-ci and
#     post-deploy-pages-verify.
# P1: optional branch protection required checks (needs admin:repo hook).
#
# Usage (from repository root, with gh authenticated):
#   bash scripts/ci/bootstrap_github_gate.sh
#   bash scripts/ci/bootstrap_github_gate.sh --dry-run
#   APPLY_BRANCH_PROTECTION=true bash scripts/ci/bootstrap_github_gate.sh
#
# Optional env for Pages post-deploy variables (skip if unset):
#   BOOTSTRAP_DEPLOY_FRONTEND_BASE_URL=https://app.example.com
#   BOOTSTRAP_DEPLOY_BASE_URL=https://api.example.com
#
# Manual (cannot be scripted without a PAT you create in GitHub UI):
#   Secret BRANCH_PROTECTION_READ_TOKEN — fine-grained PAT, Administration:Read
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

cd "$PROJECT_ROOT"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

REQUIRED_CHECKS_FILE="$PROJECT_ROOT/scripts/ci/required_status_checks.txt"
E2E_SMOKE_USER_VALUE="${BOOTSTRAP_E2E_SMOKE_USER:-seed_admin}"
E2E_SMOKE_PASS_VALUE="${BOOTSTRAP_E2E_SMOKE_PASS:-SeedPass123!}"

run_gh() {
    if [[ "$DRY_RUN" == "true" ]]; then
        printf '[dry-run] gh %s\n' "$*"
        return 0
    fi
    gh "$@"
}

require_cmd gh

if ! gh auth status >/dev/null 2>&1; then
    log_error "gh is not authenticated. Run: gh auth login"
    exit 1
fi

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
log_section "Bootstrapping GitHub gate settings for $REPO (P0 + P1)"

log_section "P0 — repository secrets (Actions + Dependabot)"
log_info "Setting E2E_SMOKE_USER (default: seed_admin; override with BOOTSTRAP_E2E_SMOKE_USER)"
run_gh secret set E2E_SMOKE_USER --body "$E2E_SMOKE_USER_VALUE"
run_gh secret set E2E_SMOKE_USER --app dependabot --body "$E2E_SMOKE_USER_VALUE"
log_info "Setting E2E_SMOKE_PASS (must stay in sync with scripts/seed/dev_seed.py SEED_PASSWORD)"
run_gh secret set E2E_SMOKE_PASS --body "$E2E_SMOKE_PASS_VALUE"
run_gh secret set E2E_SMOKE_PASS --app dependabot --body "$E2E_SMOKE_PASS_VALUE"

log_warn "BRANCH_PROTECTION_READ_TOKEN must be created manually in GitHub UI:"
log_warn "  Settings → Secrets → Actions → New repository secret"
log_warn "  Value: fine-grained PAT with Administration:Read on this repository"
log_warn "  Used by: .github/workflows/guard-branch-protection.yml"

log_section "P0 — repository variables (optional)"
if [[ -n "${BOOTSTRAP_DEPLOY_FRONTEND_BASE_URL:-}" ]]; then
    run_gh variable set DEPLOY_FRONTEND_BASE_URL --body "$BOOTSTRAP_DEPLOY_FRONTEND_BASE_URL"
else
    log_info "Skipping DEPLOY_FRONTEND_BASE_URL (set BOOTSTRAP_DEPLOY_FRONTEND_BASE_URL to configure)"
fi
if [[ -n "${BOOTSTRAP_DEPLOY_BASE_URL:-}" ]]; then
    run_gh variable set DEPLOY_BASE_URL --body "$BOOTSTRAP_DEPLOY_BASE_URL"
else
    log_info "Skipping DEPLOY_BASE_URL (set BOOTSTRAP_DEPLOY_BASE_URL to configure)"
fi

log_section "P1 — required status checks (reference list)"
grep -v '^[[:space:]]*#' "$REQUIRED_CHECKS_FILE" | grep -v '^[[:space:]]*$' | sed 's/^/  - /'

if [[ "${APPLY_BRANCH_PROTECTION:-false}" != "true" ]]; then
    log_info "Branch protection not modified (set APPLY_BRANCH_PROTECTION=true to apply via API)"
    log_info "Or configure manually: Settings → Branches → main → Required status checks"
    exit 0
fi

log_section "P1 — applying branch protection required checks"

if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[dry-run] Would PATCH branch protection for main with contexts from $REQUIRED_CHECKS_FILE"
    exit 0
fi

mapfile -t required_contexts < <(
    grep -v '^[[:space:]]*#' "$REQUIRED_CHECKS_FILE" | grep -v '^[[:space:]]*$'
)

checks_json="$(printf '%s\n' "${required_contexts[@]}" | jq -Rn '
    [inputs | select(length > 0)] | map({context: ., app_id: null})
')"

payload="$(jq -n \
    --argjson checks "$checks_json" \
    '{
        required_status_checks: {
            strict: true,
            checks: $checks
        },
        enforce_admins: false,
        required_pull_request_reviews: {
            dismiss_stale_reviews: false,
            require_code_owner_reviews: false,
            required_approving_review_count: 0
        },
        restrictions: null,
        required_linear_history: false,
        allow_force_pushes: false,
        allow_deletions: false,
        block_creations: false,
        required_conversation_resolution: false,
        lock_branch: false,
        allow_fork_syncing: true
    }'
)"

log_info "Updating branch protection for main (requires admin:repo hook)"
require_cmd jq
printf '%s\n' "$payload" | gh api "repos/$REPO/branches/main/protection" -X PUT --input -

log_section "Bootstrap complete"
log_info "Verify in GitHub: Settings → Branches → main → Required status checks"
