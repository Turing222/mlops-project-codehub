#!/usr/bin/env bash
# Orchestrate first-time production bootstrap steps that are already scripted
# in this repository. Does not create Cloudflare Tunnel/Pages resources or AWS
# infrastructure — see deploy/CHECKLIST.md and deploy/cloudflare/README.md.
#
# Usage (from repository root):
#   bash scripts/deploy/bootstrap-prod.sh ec2-stack
#   bash scripts/deploy/bootstrap-prod.sh ec2-stack --verify
#   bash scripts/deploy/bootstrap-prod.sh github-gate
#   bash scripts/deploy/bootstrap-prod.sh verify-pages
#   bash scripts/deploy/bootstrap-prod.sh --help
#
# Environment (optional):
#   SKIP_CLOUDWATCH_SETUP=1     Skip make deploy-cloudwatch-setup
#   APPLY_BRANCH_PROTECTION=true  Passed through to bootstrap_github_gate.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

cd "$PROJECT_ROOT"

usage() {
    cat <<'EOF'
Usage: bash scripts/deploy/bootstrap-prod.sh <command> [options]

Commands:
  ec2-stack       On EC2: secrets → CloudWatch (optional) → check → up → wait
                  Add --verify to run deploy-ec2-verify (needs uv on host).
  github-gate     From dev machine: bootstrap GitHub secrets/vars (needs gh).
                  Set APPLY_BRANCH_PROTECTION=true to patch main protection.
  verify-pages    Run make verify-pages (needs public DEPLOY_* origins).

Examples:
  bash scripts/deploy/bootstrap-prod.sh ec2-stack
  bash scripts/deploy/bootstrap-prod.sh ec2-stack --verify
  BOOTSTRAP_DEPLOY_BASE_URL=https://api.example.com \
  BOOTSTRAP_DEPLOY_FRONTEND_BASE_URL=https://app.example.com \
    bash scripts/deploy/bootstrap-prod.sh github-gate
  make verify-pages DEPLOY_BASE_URL=https://api.example.com \
    DEPLOY_FRONTEND_BASE_URL=https://app.example.com

See deploy/CHECKLIST.md for the full manual steps (Tunnel, Pages, DNS).
EOF
}

run_make() {
    log_info "→ make $*"
    make "$@"
}

bootstrap_ec2_stack() {
    local run_verify=false

    for arg in "$@"; do
        case "$arg" in
            --verify)
                run_verify=true
                ;;
            *)
                log_error "Unknown ec2-stack option: $arg"
                usage
                exit 1
                ;;
        esac
    done

    log_section "Bootstrap EC2 application stack"
    run_make deploy-ec2-secrets-prepare

    if [[ "${SKIP_CLOUDWATCH_SETUP:-}" != "1" ]]; then
        if command -v aws >/dev/null 2>&1; then
            run_make deploy-cloudwatch-setup
        else
            log_warn "aws CLI not found; skipping deploy-cloudwatch-setup (set SKIP_CLOUDWATCH_SETUP=1 to silence)"
        fi
    else
        log_info "Skipping deploy-cloudwatch-setup (SKIP_CLOUDWATCH_SETUP=1)"
    fi

    run_make deploy-ec2-check
    run_make deploy-ec2-up
    run_make deploy-ec2-wait

    if [[ "$run_verify" == "true" ]]; then
        if command -v uv >/dev/null 2>&1; then
            run_make deploy-ec2-verify
        else
            log_warn "uv not found; skipping deploy-ec2-verify (install uv or run manually later)"
        fi
    fi

    log_section "EC2 stack bootstrap complete"
    log_info "Next: configure Cloudflare Tunnel (deploy/cloudflare/README.md), then Pages + domains (deploy/CHECKLIST.md Phase 4–5)"
}

bootstrap_github_gate() {
    log_section "Bootstrap GitHub gate settings"
    require_cmd gh
    bash scripts/ci/bootstrap_github_gate.sh
}

bootstrap_verify_pages() {
    log_section "Verify Cloudflare Pages release contract"
    run_make verify-pages
}

command="${1:-}"
shift || true

case "$command" in
    ec2-stack)
        bootstrap_ec2_stack "$@"
        ;;
    github-gate)
        bootstrap_github_gate
        ;;
    verify-pages)
        bootstrap_verify_pages
        ;;
    -h|--help|help|"")
        usage
        ;;
    *)
        log_error "Unknown command: $command"
        usage
        exit 1
        ;;
esac
